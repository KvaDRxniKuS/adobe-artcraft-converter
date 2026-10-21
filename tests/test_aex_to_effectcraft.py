"""Static .aex recognition + independent EffectCraft WASM delivery tests."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

from aex_to_effectcraft import convert_aex, inspect_aex, main, output_stem
from effectcraft_pixel_sorter import MANIFEST, MANIFEST_SHA256, WASM, WASM_SHA256

ROOT = Path(__file__).resolve().parents[1]
REAL_AEX = Path('/tmp/arena-coding-uploads/AEPixelSorter2.aex.txt')
REAL_INSTALLER = Path('/tmp/arena-coding-uploads/Setup.exe.txt')


def sample_aex() -> bytes:
    """Synthetic PE export table + names; contains no executable code."""
    data = bytearray(2048)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3c, 0x80)
    data[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HHIIIHH', data, 0x84, 0x8664, 1, 1680000000, 0, 0, 0xf0, 0x2022)
    opt = 0x98
    struct.pack_into('<H', data, opt, 0x20b)
    struct.pack_into('<II', data, opt + 112, 0x1000, 0x80)
    sec = opt + 0xf0
    data[sec:sec + 8] = b'.edata\0\0'
    struct.pack_into('<IIII', data, sec + 8, 0x400, 0x1000, 0x400, 0x200)
    struct.pack_into('<I', data, 0x200 + 24, 2)
    struct.pack_into('<I', data, 0x200 + 32, 0x1050)
    struct.pack_into('<II', data, 0x250, 0x1080, 0x1090)
    data[0x280:0x28b] = b'EffectMain\0'
    data[0x290:0x2a8] = b'PluginDataEntryFunction\0'
    data[0x400:0x400 + 83] = (b'GG AEPixelSorter2\0Sort by\0Trigger\0Threshold\0'
                                b'Feather Start\0Feather End\0')
    return bytes(data)


class AexTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.base = Path(self.folder.name)
        self.source = self.base / 'Sample.aex.txt'
        self.source.write_bytes(sample_aex())
        self.output = self.base / 'Sample_effectcraft.wasm'

    def test_recognizes_pe_exports_and_settings(self):
        info = inspect_aex(self.source)
        self.assertEqual(info.exports, ('EffectMain', 'PluginDataEntryFunction'))
        self.assertEqual(info.size, len(sample_aex()))
        self.assertEqual(info.sha256, hashlib.sha256(sample_aex()).hexdigest())
        self.assertIn('Feather Start', info.labels)
        self.assertEqual(output_stem(self.source), 'Sample')

    def test_converts_to_identical_embedded_wasm_with_cautionary_report(self):
        report = convert_aex(self.source, self.output, language='en')
        self.assertEqual(self.output.read_bytes(), WASM)
        text = report.read_text(encoding='utf-8')
        for word in ('NOT a binary translation', 'not included, executed',
                     'visual parity is unverified', 'EffectCraft'):
            self.assertIn(word, text)
        self.assertIn(self.source.name, text)
        self.assertNotIn(b'GG AEPixelSorter2\0', self.output.read_bytes())

    def test_refuses_unknown_or_corrupt_pe_without_writing(self):
        for name, blob in (
            ('text', b'hello'),
            ('installer', sample_aex()[:0x84] + b'\x4c\x01' + sample_aex()[0x86:]),
            ('bad_marker', sample_aex().replace(b'GG AEPixelSorter2', b'YY AEPixelSorter2')),
            ('no_export', sample_aex().replace(b'EffectMain', b'InvalidExp!')),
            ('bad_export_rva', sample_aex()[:0x108] + b'\xff\xff\xff\xff' + sample_aex()[0x10c:]),
        ):
            with self.subTest(name=name):
                self.source.write_bytes(blob)
                with self.assertRaises(ValueError):
                    convert_aex(self.source, self.output)
                self.assertFalse(self.output.exists())
                self.assertFalse(self.base.joinpath('Sample_effectcraft_conversion_report.md').exists())
        self.source.write_bytes(sample_aex())

    def test_never_overwrites_input_output_or_existing_report(self):
        report = self.output.with_name(self.output.stem + '_conversion_report.md')
        for target, existing in ((self.output, self.output), (report, report)):
            with self.subTest(target=target):
                existing.write_text('do not overwrite', encoding='utf-8')
                with self.assertRaises(FileExistsError):
                    convert_aex(self.source, self.output)
                self.assertEqual(existing.read_text(encoding='utf-8'), 'do not overwrite')
                if existing == self.output:
                    self.assertFalse(report.exists())
                existing.unlink()
        renamed_input = self.base / 'source.wasm'
        renamed_input.write_bytes(sample_aex())
        with self.assertRaisesRegex(ValueError, 'исходный'):
            convert_aex(renamed_input, renamed_input)
        self.assertEqual(renamed_input.read_bytes(), sample_aex())
        with self.assertRaises(ValueError):
            convert_aex(self.source, self.base / 'wrong.txt')

    def test_cli_default_output_and_report(self):
        self.assertEqual(main([str(self.source), '--language', 'en']), 0)
        self.assertEqual(self.output.read_bytes(), WASM)
        self.assertTrue(self.base.joinpath('Sample_effectcraft_conversion_report.md').is_file())

    def test_embedded_asset_matches_build_source_and_deliverable(self):
        self.assertEqual(hashlib.sha256(WASM).hexdigest(), WASM_SHA256)
        meta = json.dumps(MANIFEST, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        self.assertEqual(hashlib.sha256(meta).hexdigest(), MANIFEST_SHA256)
        self.assertEqual(MANIFEST, json.loads(
            (ROOT / 'effectcraft_plugins/pixel_sorter_manifest.json').read_text(encoding='utf-8')))
        binary = ROOT / 'effectcraft_plugins/PixelSorter_EffectCraft.wasm'
        self.assertEqual(WASM, binary.read_bytes())

    def test_manifest_matches_effectcraft_plugin_api_v1_parameter_schema(self):
        self.assertEqual(MANIFEST['api'], 1)
        self.assertTrue(re.fullmatch(r'[A-Za-z0-9_.-]+', MANIFEST['id']))
        self.assertFalse(MANIFEST['id'].startswith('ec.'))
        ids = [p['id'] for p in MANIFEST['params']]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), 18)
        for param in MANIFEST['params']:
            with self.subTest(param=param['id']):
                self.assertRegex(param['id'], r'^[A-Za-z0-9_]+$')
                if param['type'] == 'popup':
                    self.assertTrue(param['options'])
                    self.assertLess(param['default'], len(param['options']))
                    self.assertGreaterEqual(param['default'], 0)
                elif param['type'] == 'slider':
                    self.assertLessEqual(param['min'], param['default'])
                    self.assertLessEqual(param['default'], param['max'])
                else:
                    self.assertIn(param['type'], ('checkbox', 'angle'))

    @unittest.skipUnless(shutil.which('node'), 'Node.js needed to execute the WebAssembly smoke tests')
    def test_wasm_render_in_real_webassembly_runtime(self):
        completed = subprocess.run(['node', str(ROOT / 'tests/effectcraft_wasm_smoke.cjs')],
                                   cwd=ROOT, capture_output=True, text=True, timeout=50)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn('PASS', completed.stdout)

    @unittest.skipUnless(importlib.util.find_spec('wasmtime'),
                         'Optional Wasmtime runtime is not installed')
    def test_wasm_render_in_second_engine_with_frame_fuel_budget(self):
        import wasmtime
        config = wasmtime.Config()
        config.consume_fuel = True
        engine = wasmtime.Engine(config)
        module = wasmtime.Module(engine, WASM)
        self.assertEqual(list(module.imports), [])
        store = wasmtime.Store(engine)
        budget = 50_000_000 + 20_000 * 4  # EffectCraft host's frame budget.
        store.set_fuel(budget)
        exports = wasmtime.Instance(store, module, []).exports(store)
        memory = exports['memory']
        params = [float(p['default']) for p in MANIFEST['params']]
        params[4] = 0  # Select every nontransparent pixel.
        grays = [0.8, 0.2, 0.6, 0.4]
        data = (b''.join(struct.pack('<d', p) for p in params)
                + b''.join(struct.pack('<4f', x, x, x, 1.0) for x in grays))
        base = exports['ec_alloc'](store, len(data))
        memory.write(store, data, base)
        rc = exports['ec_render'](store, base + len(params) * 8, 4, 1, base,
                                  len(params), 0.0, 1.0)
        self.assertEqual(rc, 0)
        self.assertGreater(store.get_fuel(), 0)
        result = [struct.unpack('<f', memory.read(store, base + len(params) * 8 + i * 16,
                                                  base + len(params) * 8 + i * 16 + 4))[0]
                  for i in range(4)]
        for got, expected in zip(result, sorted(grays)):
            self.assertAlmostEqual(got, expected, places=5)

    @unittest.skipUnless(REAL_INSTALLER.is_file(), 'Installer only available in the Arena session')
    def test_installer_is_rejected_without_running_it(self):
        with self.assertRaisesRegex(ValueError, '64-битный'):
            inspect_aex(REAL_INSTALLER)  # Static read only; never use subprocess on it.

    @unittest.skipUnless(REAL_AEX.is_file(), 'User-supplied .aex only available in the Arena session')
    def test_user_supplied_aex_identification(self):
        info = inspect_aex(REAL_AEX)
        self.assertEqual(info.sha256, '57f8a35fe255986013e43acfd1a9fd1665ca6e1a041025f71d52a010ebbe2d3f')
        self.assertEqual(info.size, 5335552)
        report = convert_aex(REAL_AEX, self.output)
        self.assertEqual(self.output.read_bytes(), WASM)
        self.assertIn(info.sha256, report.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
