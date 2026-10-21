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

from converters.aex_to_effectcraft import (UnsupportedAexError, bounds_script_path, convert_aex,
                                inspect_aex, main, output_stem)
from craft_converter.deep_glow_bounds import SCRIPT as BOUNDS_SCRIPT
from craft_converter.deep_glow_defaults import customized_wasm, padded_manifest
from craft_converter.effectcraft_pixel_sorter import MANIFEST, MANIFEST_SHA256, WASM, WASM_SHA256
from craft_converter.effectcraft_deep_glow import (MANIFEST as GLOW_MANIFEST, MANIFEST_SHA256 as GLOW_MANIFEST_SHA256,
                                   WASM as GLOW_WASM, WASM_SHA256 as GLOW_SHA256)

ROOT = Path(__file__).resolve().parents[1]
REAL_AEX = Path('/tmp/arena-coding-uploads/AEPixelSorter2.aex.txt')
REAL_GLOW = Path('/tmp/arena-coding-uploads/Deep Glow.aex.txt')
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


def sample_deep_glow() -> bytes:
    """Synthetic identity strings only; no vendor executable code or assets."""
    data = bytearray(sample_aex())
    labels = (b'Deep Glow 2\0Deep Glow\0Radius\0Exposure\0'
              b'Threshold\0Threshold Smooth\0Blend Mode\0Spread\0')
    data[0x400:0x400 + 120] = labels.ljust(120, b'\0')
    return bytes(data)


def sample_profile(effect_name='Novel Glow', match_name='vendor.novel') -> dict:
    return {
        'format': 'artcraft.ae-parameter-profile', 'version': 1,
        'effect_name': effect_name, 'effect_match_name': match_name,
        'properties': [{
            'name': 'Radius', 'match_name': 'vendor.radius',
            'groups': ['Glow', 'Main'], 'value_type': 'scalar',
            'has_min': True, 'min_value': 0,
            'has_max': False, 'max_value': None,
            'can_vary_over_time': True, 'can_set_expression': False,
            'ui_control': 'unknown',
        }],
    }


def sample_values(match_name='PEDG') -> dict:
    return {
        'format': 'artcraft.ae-effect-values', 'version': 1,
        'effect_name': 'Deep Glow 2', 'effect_match_name': match_name,
        'properties': [
            {'name': name, 'match_name': f'PEDG-{i:04d}', 'groups': ['Glow'],
             'value_type': 'scalar', 'value': value}
            for i, (name, value) in enumerate((
                ('Radius', 512), ('Exposure', 2.5), ('Threshold', 42),
                ('Threshold Smooth', 30), ('Spread', 72),
                ('Source Opacity', 84), ('Blend Mode', 1), ('Mix', 55)))
        ],
    }


def sample_with_pipl(source: bytes, name: str, category: str,
                     match_name: str = 'example.match') -> bytes:
    """Add a small real PE resource tree with AE PiPL name/category/match id."""
    data = bytearray(source)
    data.extend(bytes(max(0, 0x800 - len(data))))
    pe = 0x80
    struct.pack_into('<H', data, pe + 6, 2)  # .edata + .rsrc
    opt = pe + 24
    struct.pack_into('<II', data, opt + 112 + 2 * 8, 0x2000, 0x200)
    sec = opt + 0xf0 + 40
    data[sec:sec + 8] = b'.rsrc\0\0\0'
    struct.pack_into('<IIII', data, sec + 8, 0x200, 0x2000, 0x200, 0x600)
    base = 0x600
    struct.pack_into('<HHII', data, base + 12, 1, 0, 0x800000a0, 0x80000020)
    struct.pack_into('<HHII', data, base + 0x20 + 12, 0, 1, 0x3e80, 0x80000050)
    struct.pack_into('<HHII', data, base + 0x50 + 12, 0, 1, 0x409, 0x80)
    data[base + 0xa0:base + 0xaa] = struct.pack('<H', 4) + 'PIPL'.encode('utf-16le')
    entries = []
    for key, label in ((b'eman', name), (b'gtac', category), (b'ANMe', match_name)):
        encoded = label.encode('ascii')
        value = bytes([len(encoded)]) + encoded
        value += bytes((-len(value)) % 4)
        entries.append(b'MIB8' + key + bytes(4) + struct.pack('<I', len(value)) + value)
    blob = struct.pack('<IH', 1, 0) + struct.pack('<I', len(entries)) + b''.join(entries)
    assert len(blob) < 0x130
    struct.pack_into('<II', data, base + 0x80, 0x20c0, len(blob))
    data[base + 0xc0:base + 0xc0 + len(blob)] = blob
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
        self.assertEqual(info.family, 'pixel_sorter')
        self.assertEqual(info.architecture, 'x64')
        self.assertEqual(output_stem(self.source), 'Sample')

    def test_pipl_identifies_an_unknown_effect_without_inventing_controls(self):
        data = sample_aex().replace(b'GG AEPixelSorter2', b'YY AEPixelSorter2')
        self.source.write_bytes(sample_with_pipl(data, 'Novel Glow', 'Custom', 'vendor.novel'))
        info = inspect_aex(self.source)
        self.assertIsNone(info.family)
        self.assertEqual(info.pipl_effects[0].name, 'Novel Glow')
        self.assertEqual(info.pipl_effects[0].category, 'Custom')
        self.assertEqual(info.pipl_effects[0].match_name, 'vendor.novel')
        with self.assertRaises(UnsupportedAexError) as outcome:
            convert_aex(self.source, self.output, language='en')
        self.assertFalse(self.output.exists())
        report = outcome.exception.report.read_text(encoding='utf-8')
        self.assertIn('Novel Glow [Custom; vendor.novel]', report)
        self.assertIn('bounds', report)
        self.assertIn('group hierarchy', report)
        self.assertIn('keyframe/curve capabilities cannot be verified', report)

    def test_optional_ae_host_profile_reports_bounds_groups_and_keyframes(self):
        source = sample_aex().replace(b'GG AEPixelSorter2', b'YY AEPixelSorter2')
        self.source.write_bytes(sample_with_pipl(source, 'Novel Glow', 'Custom', 'vendor.novel'))
        profile = self.base / 'ae_profile.json'
        profile.write_text(json.dumps(sample_profile()), encoding='utf-8')
        with self.assertRaises(UnsupportedAexError) as outcome:
            convert_aex(self.source, self.output, language='en', ae_profile=profile)
        self.assertFalse(self.output.exists())  # Metadata does not invent an effect.
        text = outcome.exception.report.read_text(encoding='utf-8')
        self.assertIn('cross-checked against the DLL PiPL: yes', text)
        self.assertIn('Glow › Main › Radius', text)
        self.assertIn('min 0.0; max none; keyframes yes; expressions no', text)
        self.assertIn('UI widget unknown', text)
        self.assertIn('no WASM created', text)
        outcome.exception.report.unlink()
        self.assertEqual(main([str(self.source), str(self.output), '--language', 'en',
                               '--ae-profile', str(profile)]), 2)
        self.assertFalse(self.output.exists())
        self.output.with_name(self.output.stem + '_aex_analysis.md').unlink()

        # A matching known port still exports its independently written WASM;
        # the AE-host observations are reported, never applied to its renderer.
        self.source.write_bytes(sample_with_pipl(sample_deep_glow(),
                                                 'Deep Glow', 'Stylize', 'PEDG'))
        profile.write_text(json.dumps(sample_profile('Deep Glow', 'PEDG')), encoding='utf-8')
        report = convert_aex(self.source, self.output, language='en', ae_profile=profile)
        self.assertEqual(self.output.read_bytes(), GLOW_WASM)
        self.assertIn('Glow › Main › Radius', report.read_text(encoding='utf-8'))

    def test_ae_numeric_snapshot_changes_only_known_deep_glow_defaults(self):
        self.source.write_bytes(sample_with_pipl(sample_deep_glow(),
                                                 'Deep Glow', 'Stylize', 'PEDG'))
        snapshot = self.base / 'deep_glow_values.json'
        snapshot.write_text(json.dumps(sample_values()), encoding='utf-8')
        report = convert_aex(self.source, self.output, language='en', ae_values=snapshot)
        wasm = self.output.read_bytes()
        self.assertNotEqual(wasm, GLOW_WASM)
        self.assertEqual(len(wasm), len(GLOW_WASM))
        self.assertTrue(wasm.startswith(b'\0asm'))
        expected = {'radius': 512, 'exposure': 2.5, 'threshold': 42,
                    'threshold_smooth': 30, 'spread': 72, 'source_opacity': 84}
        patched, manifest = customized_wasm(GLOW_WASM, GLOW_MANIFEST, expected)
        self.assertEqual(wasm, patched)
        self.assertIn(padded_manifest(manifest), wasm)
        self.assertNotIn(padded_manifest(GLOW_MANIFEST), wasm)
        self.assertEqual([p['default'] for p in GLOW_MANIFEST['params'][:2]], [48, 1.5])
        self.assertEqual(bounds_script_path(self.output).read_text(encoding='utf-8'), BOUNDS_SCRIPT)
        text = report.read_text(encoding='utf-8')
        self.assertIn('`radius` = 512', text)
        self.assertIn('`threshold_smooth` = 30', text)
        self.assertIn('Blend Mode: no verified one-to-one port control', text)
        self.assertIn('Factory defaults only if the effect was freshly added', text)
        self.assertIn('grow', text.lower())
        self.assertIn(hashlib.sha256(wasm).hexdigest(), text)

    def test_invalid_snapshot_is_rejected_without_writing_any_result(self):
        self.source.write_bytes(sample_with_pipl(sample_deep_glow(),
                                                 'Deep Glow', 'Stylize', 'PEDG'))
        snapshot = self.base / 'snapshot.json'
        examples = [
            (sample_profile('Deep Glow', 'PEDG'), 'Unknown AE settings snapshot format'),
            ({**sample_values(), 'project_path': 'private.aep'}, 'Unexpected AE settings fields'),
            (sample_values('another.plugin'), 'not from Deep Glow'),
        ]
        for payload, message in examples:
            with self.subTest(message=message):
                snapshot.write_text(json.dumps(payload), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, message):
                    convert_aex(self.source, self.output, ae_values=snapshot)
                self.assertFalse(self.output.exists())
                self.assertFalse(bounds_script_path(self.output).exists())
        payload = sample_values()
        payload['properties'][0]['value'] = float('nan')
        snapshot.write_text(json.dumps(payload), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'numeric value'):
            convert_aex(self.source, self.output, ae_values=snapshot)
        self.assertFalse(self.output.exists())

    def test_wasm_manifest_patch_rejects_unreserved_or_bad_defaults(self):
        for overrides, message in (
            ({'unknown': 1}, 'Unknown Deep Glow parameter'),
            ({'radius': -1}, 'outside the port range'),
            ({'radius': True}, 'finite number'),
            ({'radius': 10 ** 1000}, 'finite number'),
            ({'quality': 7}, 'valid popup index'),
            ({'expand_alpha': 1}, 'must be boolean'),
        ):
            with self.subTest(overrides=overrides), self.assertRaisesRegex(ValueError, message):
                customized_wasm(GLOW_WASM, GLOW_MANIFEST, overrides)
        with self.assertRaisesRegex(RuntimeError, 'layout'):
            customized_wasm(b'\0asm' + b'not our compiled module', GLOW_MANIFEST,
                            {'radius': 11})

    def test_settings_out_of_range_or_ambiguous_are_not_silently_clamped(self):
        self.source.write_bytes(sample_deep_glow())
        snapshot = self.base / 'snapshot.json'
        data = sample_values()
        data['properties'][0]['value'] = 2e9  # Larger than the port's finite API max.
        data['properties'].append({**data['properties'][1], 'match_name': 'PEDG-other'})
        snapshot.write_text(json.dumps(data), encoding='utf-8')
        report = convert_aex(self.source, self.output, language='en', ae_values=snapshot)
        self.assertIn('outside the port range', report.read_text(encoding='utf-8'))
        self.assertIn('ambiguous source value', report.read_text(encoding='utf-8'))
        _, manifest = customized_wasm(GLOW_WASM, GLOW_MANIFEST,
                                      {'threshold': 42, 'threshold_smooth': 30,
                                       'spread': 72, 'source_opacity': 84})
        self.assertIn(padded_manifest(manifest), self.output.read_bytes())

    def test_ae_profile_without_pipl_does_not_claim_a_cross_check(self):
        # The AE script can inventory an effect even when a PiPL is absent or
        # inaccessible; never turn missing evidence into a false mismatch.
        self.source.write_bytes(sample_deep_glow())
        profile = self.base / 'ae_profile.json'
        profile.write_text(json.dumps(sample_profile('Deep Glow', 'PEDG')), encoding='utf-8')
        report = convert_aex(self.source, self.output, language='en', ae_profile=profile)
        self.assertIn('cross-checked against the DLL PiPL: unknown',
                      report.read_text(encoding='utf-8'))

    def test_profile_must_match_declared_effect_and_not_contain_values(self):
        self.source.write_bytes(sample_with_pipl(sample_deep_glow(),
                                                 'Deep Glow', 'Stylize', 'PEDG'))
        profile = self.base / 'ae_profile.json'
        profile.write_text(json.dumps(sample_profile()), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'does not match'):
            convert_aex(self.source, self.output, ae_profile=profile)
        self.assertFalse(self.output.exists())
        data = sample_profile('Deep Glow', 'PEDG')
        data['properties'][0]['value'] = 42
        profile.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'values are forbidden'):
            convert_aex(self.source, self.output, ae_profile=profile)
        self.assertFalse(self.output.exists())
        data['properties'][0].pop('value')
        data['properties'][0]['ui_control'] = 'slider'  # AE script cannot verify this.
        profile.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'must be marked unknown'):
            convert_aex(self.source, self.output, ae_profile=profile)
        self.assertFalse(self.output.exists())
        profile_wasm = self.base / 'ae_profile.wasm'
        profile_wasm.write_text(json.dumps(sample_profile('Deep Glow', 'PEDG')), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'не должен перезаписывать'):
            convert_aex(self.source, profile_wasm, ae_profile=profile_wasm)

    def test_pipl_identity_prevents_a_false_known_port(self):
        self.source.write_bytes(sample_with_pipl(sample_deep_glow(), 'Different Effect', 'Custom'))
        self.assertIsNone(inspect_aex(self.source).family)
        with self.assertRaises(UnsupportedAexError):
            convert_aex(self.source, self.output)
        self.assertFalse(self.output.exists())
        self.source.write_bytes(sample_with_pipl(sample_deep_glow(), 'Deep Glow',
                                                 'Stylize', 'example.match'))
        self.assertIsNone(inspect_aex(self.source).family)  # Same label, wrong plug-in.
        self.source.write_bytes(sample_with_pipl(sample_deep_glow(), 'Deep Glow',
                                                 'Stylize', 'PEDG'))
        self.assertEqual(inspect_aex(self.source).family, 'deep_glow')

    def test_damaged_optional_pipl_is_ignored_without_executing_it(self):
        data = bytearray(sample_with_pipl(sample_deep_glow(), 'Deep Glow', 'Stylize'))
        struct.pack_into('<I', data, 0x600 + 0x80, 0xffffffff)
        self.source.write_bytes(data)
        info = inspect_aex(self.source)
        self.assertEqual(info.pipl_effects, ())
        self.assertEqual(info.family, 'deep_glow')  # Existing label fallback still works.

    def test_different_binaries_with_same_known_identity_use_one_independent_port(self):
        """The AEX selects a prewritten port; its machine code is never lifted."""
        first_hash = inspect_aex(self.source).sha256
        convert_aex(self.source, self.output)
        other = self.base / 'OtherBuild.aex'
        modified = bytearray(sample_aex())
        modified[0x380] ^= 0x42  # PE payload differs; export table and identity do not.
        other.write_bytes(modified)
        self.assertNotEqual(first_hash, inspect_aex(other).sha256)
        second = self.base / 'OtherBuild.wasm'
        convert_aex(other, second)
        self.assertEqual(self.output.read_bytes(), second.read_bytes())
        self.assertEqual(second.read_bytes(), WASM)

    def test_converts_to_identical_embedded_wasm_with_cautionary_report(self):
        report = convert_aex(self.source, self.output, language='en')
        self.assertEqual(self.output.read_bytes(), WASM)
        text = report.read_text(encoding='utf-8')
        for word in ('NOT a binary translation', 'not included, executed',
                     'visual parity is unverified', 'EffectCraft'):
            self.assertIn(word, text)
        self.assertIn(self.source.name, text)
        self.assertNotIn(b'GG AEPixelSorter2\0', self.output.read_bytes())

    def test_deep_glow_has_distinct_working_wasm_and_report(self):
        self.source.write_bytes(sample_deep_glow())
        info = inspect_aex(self.source)
        self.assertEqual(info.family, 'deep_glow')
        self.assertIn('Radius', info.labels)
        self.assertEqual(info.architecture, 'x64')
        report = convert_aex(self.source, self.output, language='en')
        self.assertEqual(self.output.read_bytes(), GLOW_WASM)
        self.assertNotEqual(self.output.read_bytes(), WASM)
        report_text = report.read_text(encoding='utf-8')
        self.assertIn('multi-scale bloom', report_text)
        self.assertIn('Gaussian-like', report_text)
        self.assertIn('16 times the longest frame dimension', report_text)
        self.assertIn('Quit EffectCraft', report_text)
        self.assertIn('NOT the original', report_text)
        self.assertIn('The WASM alone cannot draw outside the source footage rectangle', report_text)
        self.assertEqual(bounds_script_path(self.output).read_text(encoding='utf-8'), BOUNDS_SCRIPT)
        self.assertNotIn(b'Deep Glow 2\0', self.output.read_bytes())

    def test_unknown_effect_is_analyzed_without_faking_a_wasm(self):
        for name, blob in (
            ('unrecognized', sample_aex().replace(b'GG AEPixelSorter2', b'YY AEPixelSorter2')),
            ('different_exports', sample_aex().replace(b'EffectMain', b'InvalidExp!')),
        ):
            with self.subTest(name=name):
                self.source.write_bytes(blob)
                info = inspect_aex(self.source)
                self.assertIsNone(info.family)
                with self.assertRaises(UnsupportedAexError) as result:
                    convert_aex(self.source, self.output, language='en')
                self.assertFalse(self.output.exists())
                report = result.exception.report
                self.assertEqual(report.name, 'Sample_effectcraft_aex_analysis.md')
                text = report.read_text(encoding='utf-8')
                self.assertIn('no WASM created', text)
                self.assertIn(info.sha256, text)
                report.unlink()
        self.assertEqual(main([str(self.source), '--language', 'en']), 2)
        self.assertFalse(self.output.exists())

    def test_invalid_dll_does_not_write_wasm_or_report(self):
        for name, blob in (
            ('text', b'hello'),
            ('invalid_architecture', sample_aex()[:0x84] + b'\x4c\x01' + sample_aex()[0x86:]),
            ('bad_export_rva', sample_aex()[:0x108] + b'\xff\xff\xff\xff' + sample_aex()[0x10c:]),
        ):
            with self.subTest(name=name):
                self.source.write_bytes(blob)
                with self.assertRaises(ValueError):
                    convert_aex(self.source, self.output)
                self.assertFalse(self.output.exists())
                self.assertFalse(self.base.joinpath('Sample_effectcraft_conversion_report.md').exists())
                self.assertFalse(self.base.joinpath('Sample_effectcraft_aex_analysis.md').exists())
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

    def test_deep_glow_script_collision_prevents_partial_result(self):
        self.source.write_bytes(sample_deep_glow())
        script = bounds_script_path(self.output)
        script.write_text('Do not overwrite', encoding='utf-8')
        with self.assertRaises(FileExistsError):
            convert_aex(self.source, self.output)
        self.assertEqual(script.read_text(encoding='utf-8'), 'Do not overwrite')
        self.assertFalse(self.output.exists())
        self.assertFalse(self.output.with_name(self.output.stem + '_conversion_report.md').exists())

    def test_unknown_does_not_overwrite_existing_analysis_or_output(self):
        self.source.write_bytes(sample_aex().replace(b'GG AEPixelSorter2', b'YY AEPixelSorter2'))
        report = self.output.with_name(self.output.stem + '_aex_analysis.md')
        for existing in (self.output, report):
            with self.subTest(existing=existing):
                existing.write_text('keep existing', encoding='utf-8')
                with self.assertRaises(FileExistsError):
                    convert_aex(self.source, self.output)
                self.assertEqual(existing.read_text(encoding='utf-8'), 'keep existing')
                existing.unlink()
        self.assertFalse(self.output.exists())

    def test_x86_dll_can_be_inspected_without_artificial_x64_restriction(self):
        blob = bytearray(sample_aex().replace(b'GG AEPixelSorter2', b'YY AEPixelSorter2'))
        struct.pack_into('<H', blob, 0x84, 0x14c)  # Intel x86 machine
        struct.pack_into('<H', blob, 0x98, 0x10b)  # PE32 optional header
        struct.pack_into('<II', blob, 0x98 + 96, 0x1000, 0x80)
        struct.pack_into('<II', blob, 0x98 + 112, 0, 0)
        self.source.write_bytes(blob)
        info = inspect_aex(self.source)
        self.assertEqual(info.architecture, 'x86')
        self.assertIsNone(info.family)
        with self.assertRaises(UnsupportedAexError):
            convert_aex(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_cli_default_output_and_report(self):
        self.assertEqual(main([str(self.source), '--language', 'en']), 0)
        self.assertEqual(self.output.read_bytes(), WASM)
        self.assertTrue(self.base.joinpath('Sample_effectcraft_conversion_report.md').is_file())

    def test_cli_accepts_explicit_ae_snapshot_for_deep_glow(self):
        self.source.write_bytes(sample_deep_glow())
        values = self.base / 'ae_values.json'
        values.write_text(json.dumps(sample_values()), encoding='utf-8')
        self.assertEqual(main([str(self.source), str(self.output), '--language', 'en',
                               '--ae-values', str(values)]), 0)
        self.assertNotEqual(self.output.read_bytes(), GLOW_WASM)
        self.assertTrue(bounds_script_path(self.output).is_file())

    def test_embedded_asset_matches_build_source_and_deliverable(self):
        self.assertEqual(hashlib.sha256(WASM).hexdigest(), WASM_SHA256)
        meta = json.dumps(MANIFEST, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        self.assertEqual(hashlib.sha256(meta).hexdigest(), MANIFEST_SHA256)
        self.assertEqual(MANIFEST, json.loads(
            (ROOT / 'effectcraft_plugins/pixel_sorter_manifest.json').read_text(encoding='utf-8')))
        binary = ROOT / 'effectcraft_plugins/PixelSorter_EffectCraft.wasm'
        self.assertEqual(WASM, binary.read_bytes())

    def test_glow_embedded_asset_has_reserved_defaults_and_matches_builder_manifest(self):
        self.assertEqual(hashlib.sha256(GLOW_WASM).hexdigest(), GLOW_SHA256)
        meta = padded_manifest(GLOW_MANIFEST)
        self.assertEqual(hashlib.sha256(meta).hexdigest(), GLOW_MANIFEST_SHA256)
        self.assertEqual(GLOW_WASM.count(meta), 1)
        self.assertEqual(GLOW_MANIFEST, json.loads(
            (ROOT / 'effectcraft_plugins/deep_glow_manifest.json').read_text(encoding='utf-8')))
        self.assertEqual(GLOW_WASM, (ROOT / 'effectcraft_plugins/DeepGlow_EffectCraft.wasm').read_bytes())

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

    @unittest.skipUnless(shutil.which('node'), 'Node.js needed for JSX simulator test')
    def test_ae_host_script_exports_only_observable_metadata_in_a_mock(self):
        completed = subprocess.run(['node', str(ROOT / 'tests/ae_metadata_script_smoke.cjs')],
                                   cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn('PASS', completed.stdout)

    @unittest.skipUnless(shutil.which('node'), 'Node.js needed for simulated host tests')
    def test_ae_settings_and_effectcraft_bounds_scripts_in_host_mocks(self):
        for name in ('ae_values_script_smoke.cjs', 'deep_glow_bounds_script_smoke.cjs'):
            with self.subTest(script=name):
                completed = subprocess.run(['node', str(ROOT / 'tests' / name)],
                                           cwd=ROOT, capture_output=True, text=True, timeout=20)
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                self.assertIn('PASS', completed.stdout)
        self.assertEqual((ROOT / 'effectcraft_plugins/ApplyDeepGlowWithBounds.jsx').read_text(
            encoding='utf-8'), BOUNDS_SCRIPT)

    @unittest.skipUnless(shutil.which('node'), 'Node.js needed for customized WASM test')
    def test_converter_patched_wasm_executes_in_webassembly_runtime(self):
        self.source.write_bytes(sample_deep_glow())
        snapshot = self.base / 'snapshot.json'
        snapshot.write_text(json.dumps(sample_values()), encoding='utf-8')
        convert_aex(self.source, self.output, ae_values=snapshot)
        completed = subprocess.run(['node', str(ROOT / 'tests/deep_glow_custom_defaults_smoke.cjs'),
                                    str(self.output)], cwd=ROOT, capture_output=True, text=True,
                                   timeout=20)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn('PASS', completed.stdout)

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
        with self.assertRaisesRegex(ValueError, 'установщик'):
            inspect_aex(REAL_INSTALLER)  # Static read only; never use subprocess on it.

    @unittest.skipUnless(REAL_AEX.is_file(), 'User-supplied .aex only available in the Arena session')
    def test_user_supplied_aex_identification(self):
        info = inspect_aex(REAL_AEX)
        self.assertEqual(info.sha256, '57f8a35fe255986013e43acfd1a9fd1665ca6e1a041025f71d52a010ebbe2d3f')
        self.assertEqual(info.size, 5335552)
        self.assertEqual((info.pipl_effects[0].name, info.pipl_effects[0].match_name),
                         ('AE Pixel Sorter 2', 'GG AEPixelSorter2'))
        report = convert_aex(REAL_AEX, self.output)
        self.assertEqual(self.output.read_bytes(), WASM)
        self.assertIn(info.sha256, report.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
