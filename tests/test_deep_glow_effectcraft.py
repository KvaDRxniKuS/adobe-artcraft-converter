"""Independent Deep Glow-like EffectCraft WASM asset and runtime checks."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import struct
import subprocess
import unittest
from pathlib import Path

from aex_to_effectcraft import convert_aex, inspect_aex
from craft_converter.deep_glow_defaults import padded_manifest
from craft_converter.effectcraft_deep_glow import MANIFEST, MANIFEST_SHA256, WASM, WASM_SHA256

ROOT = Path(__file__).resolve().parents[1]
REAL_GLOW = Path('/tmp/arena-coding-uploads/Deep Glow.aex.txt')


class DeepGlowTests(unittest.TestCase):
    def test_asset_and_manifest_match_committed_sources(self):
        self.assertEqual(hashlib.sha256(WASM).hexdigest(), WASM_SHA256)
        self.assertEqual(WASM, (ROOT / 'effectcraft_plugins/DeepGlow_EffectCraft.wasm').read_bytes())
        self.assertEqual(MANIFEST, json.loads(
            (ROOT / 'effectcraft_plugins/deep_glow_manifest.json').read_text(encoding='utf-8')))
        packed = padded_manifest(MANIFEST)
        self.assertEqual(hashlib.sha256(packed).hexdigest(), MANIFEST_SHA256)
        self.assertEqual(WASM.count(packed), 1)
        self.assertEqual(MANIFEST['api'], 1)
        self.assertEqual(MANIFEST['version'], '0.4.0')
        radius = next(p for p in MANIFEST['params'] if p['id'] == 'radius')
        self.assertEqual(radius['sliderMax'], 256)
        self.assertGreater(radius['max'], radius['sliderMax'])
        self.assertEqual(MANIFEST['category'], 'Stylize')
        self.assertRegex(MANIFEST['id'], r'^[A-Za-z0-9_.-]+$')
        names = [p['id'] for p in MANIFEST['params']]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(names), 14)
        for param in MANIFEST['params']:
            self.assertRegex(param['id'], r'^[A-Za-z0-9_]+$')
            if param['type'] == 'slider':
                self.assertLessEqual(param['min'], param['default'])
                self.assertLessEqual(param['default'], param['max'])
            elif param['type'] == 'popup':
                self.assertTrue(param['options'])
                self.assertGreaterEqual(param['default'], 0)
                self.assertLess(param['default'], len(param['options']))
            else:
                self.assertEqual(param['type'], 'checkbox')
        self.assertLess(len(WASM), 512_000)

    @unittest.skipUnless(shutil.which('node'), 'Node.js needed for WASM smoke test')
    def test_real_webassembly_runtime_renders_bloom_and_preserves_alpha(self):
        process = subprocess.run(['node', str(ROOT / 'tests/deep_glow_wasm_smoke.cjs')],
                                 cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertIn('PASS', process.stdout)

    @unittest.skipUnless(importlib.util.find_spec('wasmtime'), 'Optional Wasmtime is not installed')
    def test_wasmtime_renders_within_effectcraft_frame_fuel_budget(self):
        import wasmtime
        config = wasmtime.Config()
        config.consume_fuel = True
        engine = wasmtime.Engine(config)
        module = wasmtime.Module(engine, WASM)
        self.assertEqual(list(module.imports), [])
        for side in (1, 8, 32, 128):
            for radius, quality in ((48, 1), (256, 2), (512, 2), (1e9, 2), (8, 2)):
                with self.subTest(side=side, radius=radius, quality=quality):
                    store = wasmtime.Store(engine)
                    budget = 50_000_000 + 20_000 * side * side
                    store.set_fuel(budget)
                    exp = wasmtime.Instance(store, module, []).exports(store)
                    memory = exp['memory']
                    params = [float(p['default']) for p in MANIFEST['params']]
                    params[0], params[13] = radius, quality
                    frame = b''.join(struct.pack('<4f', *((1., 1., 1., 1.)
                                                           if i == (side * side) // 2
                                                           else (0., 0., 0., 0.)))
                                     for i in range(side * side))
                    data = b''.join(struct.pack('<d', v) for v in params) + frame
                    base = exp['ec_alloc'](store, len(data))
                    memory.write(store, data, base)
                    result = exp['ec_render'](store, base + len(params)*8, side, side,
                                              base, len(params), 0., 1.)
                    self.assertEqual(result, 0)
                    self.assertGreater(store.get_fuel(), 0)

    @unittest.skipUnless(REAL_GLOW.is_file(), 'User-provided binary only exists in Arena session')
    def test_actual_user_deep_glow_static_recognition_and_conversion(self):
        import tempfile
        info = inspect_aex(REAL_GLOW)
        self.assertEqual(info.size, 1855488)
        self.assertEqual(info.sha256, '6c952b1538632605deea6cf167a3b242f490821ab008cffc7dd37f862b532c86')
        self.assertEqual(info.family, 'deep_glow')
        self.assertEqual(info.architecture, 'x64')
        self.assertEqual((info.pipl_effects[0].name, info.pipl_effects[0].match_name),
                         ('Deep Glow', 'PEDG'))
        self.assertIn('EffectMain', info.exports)
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'DeepGlow_EffectCraft.wasm'
            report = convert_aex(REAL_GLOW, output, language='en')
            self.assertEqual(output.read_bytes(), WASM)
            self.assertIn(info.sha256, report.read_text(encoding='utf-8'))
            self.assertNotIn(b'Deep Glow 2\0', output.read_bytes())


if __name__ == '__main__':
    unittest.main()
