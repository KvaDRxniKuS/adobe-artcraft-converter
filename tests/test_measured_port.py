"""Offline reference-fitting for a previously unknown AE effect, not DLL lifting."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from converters.aex_to_effectcraft import (UnsupportedAexError, convert_aex,
                                          inspect_aex, main)
from craft_converter.effectcraft_measured_lut import MANIFEST, WASM, WASM_SHA256
from craft_converter.lut_layout import (LUT_SIZE, SLOT_PREFIX, SLOT_SUFFIX,
                                        identity_lut, manifest_bytes, patch_wasm)
from craft_converter.measured_port import (CHECK_AFTER, CHECK_INPUT, INSTRUCTIONS,
                                           REFERENCE_METADATA, TRAIN_AFTER, TRAIN_INPUT,
                                           ReferenceError, fit, prepare_charts, render_rgb)
from test_aex_to_effectcraft import sample_aex, sample_with_pipl

ROOT = Path(__file__).resolve().parents[1]
PIL_AVAILABLE = importlib.util.find_spec('PIL') is not None


class MissingPillowTests(unittest.TestCase):
    def test_chart_preparation_names_the_dependency_and_the_current_interpreter(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / 'references'
            with patch.dict(sys.modules, {'PIL': None}):
                with self.assertRaisesRegex(RuntimeError, 'Pillow .*requirements.txt') as error:
                    prepare_charts(folder, aex_digest='a' * 64)
            self.assertIn(sys.executable, str(error.exception))
            self.assertEqual(list(folder.iterdir()), [])


@unittest.skipUnless(PIL_AVAILABLE, 'Pillow from config/requirements.txt is needed')
class MeasuredPortTests(unittest.TestCase):
    def setUp(self):
        from PIL import Image, ImageFilter, ImageOps
        self.Image, self.ImageFilter, self.ImageOps = Image, ImageFilter, ImageOps
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.source = self.directory / 'UnknownColour.aex'
        source = sample_aex().replace(b'GG AEPixelSorter2', b'XX AEPixelSorter2')
        self.source.write_bytes(sample_with_pipl(source, 'Test Invert', 'Color Correction',
                                                 'vendor.invert'))
        self.output = self.directory / 'Trained.wasm'
        self.references = self.directory / 'references'
        self.digest = inspect_aex(self.source).sha256
        prepare_charts(self.references, aex_digest=self.digest)
        self.assertIsNone(inspect_aex(self.source).family)

    def render_reference(self, effect):
        for before, after in ((TRAIN_INPUT, TRAIN_AFTER), (CHECK_INPUT, CHECK_AFTER)):
            with self.Image.open(self.references / before) as image:
                image = effect(image.convert('RGBA'))
                image.save(self.references / after, 'PNG')

    def invert(self, image):
        return self.ImageOps.invert(image.convert('RGB')).convert('RGBA')

    def test_preparation_keeps_existing_files_and_requires_two_ae_renders(self):
        self.assertTrue((self.references / INSTRUCTIONS).is_file())
        self.assertIn('chart_training_ae.png', (self.references / INSTRUCTIONS).read_text())
        metadata = json.loads((self.references / REFERENCE_METADATA).read_text(encoding='utf-8'))
        self.assertEqual(metadata['aex_sha256'], self.digest)
        with self.assertRaises(FileExistsError):
            prepare_charts(self.references, aex_digest=self.digest)
        with self.assertRaisesRegex(ReferenceError, 'Missing reference PNG'):
            convert_aex(self.source, self.output, reference_dir=self.references)
        self.assertFalse(self.output.exists())
        self.assertFalse((self.directory / 'Trained_conversion_report.md').exists())
        with self.assertRaisesRegex(ReferenceError, 'subfolder'):
            prepare_charts(ROOT, aex_digest=self.digest)

    def test_fits_unknown_aex_and_produces_effect_specific_wasm_and_report(self):
        self.render_reference(self.invert)
        fitted = fit(self.references, self.digest)
        self.assertTrue(fitted.accepted)
        self.assertEqual(len(fitted.table), LUT_SIZE)
        self.assertEqual(fitted.mean_error, 0.0)
        self.assertEqual(render_rgb(fitted.table, (13, 111, 200)), (242, 144, 55))
        report = convert_aex(self.source, self.output, reference_dir=self.references,
                             language='en')
        wasm = self.output.read_bytes()
        self.assertTrue(wasm.startswith(b'\x00asm'))
        self.assertNotEqual(wasm, WASM)
        self.assertEqual(len(wasm), len(WASM))
        self.assertIn(SLOT_PREFIX + fitted.table + SLOT_SUFFIX, wasm)
        self.assertNotIn(SLOT_PREFIX + identity_lut() + SLOT_SUFFIX, wasm)
        self.assertIn('ONE', report.read_text(encoding='utf-8'))
        self.assertIn('nor proven visual equivalence', report.read_text(encoding='utf-8').lower())
        self.assertIn(inspect_aex(self.source).sha256, report.read_text(encoding='utf-8'))
        self.assertIn('SHA-256', report.read_text(encoding='utf-8'))
        self.assertFalse((self.directory / 'Trained_apply_with_bounds.jsx').exists())
        with self.assertRaises(FileExistsError):
            convert_aex(self.source, self.output, reference_dir=self.references)

    def test_cli_prepare_and_fit_paths_work_without_an_ae_project(self):
        fresh = self.directory / 'fresh'
        self.assertEqual(main([str(self.source), '--prepare-reference', str(fresh)]), 0)
        with self.assertRaisesRegex(FileExistsError, 'already exist'):
            main([str(self.source), '--prepare-reference', str(fresh)])
        self.render_reference(self.invert)
        self.assertEqual(main([str(self.source), str(self.output), '--reference-dir',
                               str(self.references)]), 0)
        self.assertTrue(self.output.is_file())

    def test_node_executes_the_fitted_binary_on_opaque_and_premultiplied_pixels(self):
        if not shutil.which('node'):
            self.skipTest('Node.js optional for converter users')
        self.render_reference(self.invert)
        convert_aex(self.source, self.output, reference_dir=self.references)
        subprocess.run(['node', str(ROOT / 'tests/measured_lut_wasm_smoke.cjs'), str(self.output)],
                       check=True, capture_output=True)

    def test_second_unknown_colour_algorithm_fits_without_another_handwritten_port(self):
        from PIL import Image

        def cross_channel(image):
            r, g, b = image.convert('RGB').split()
            return Image.merge('RGB', (
                Image.blend(r, g, 0.25),
                Image.blend(r, b, 0.5),
                Image.blend(g, b, 0.7),
            )).convert('RGBA')

        self.render_reference(cross_channel)
        fitted = fit(self.references, self.digest)
        self.assertTrue(fitted.accepted, fitted.reason)
        self.assertLess(fitted.mean_error, 1.0)
        self.assertEqual(render_rgb(fitted.table, (17, 93, 220))[0], 36)
        report = convert_aex(self.source, self.output, reference_dir=self.references)
        self.assertIn('Mix', report.read_text(encoding='utf-8'))
        if shutil.which('node'):
            subprocess.run(['node', str(ROOT / 'tests/measured_lut_wasm_smoke.cjs'),
                            str(self.output), 'cross-channel'], check=True, capture_output=True)

    def test_wasmtime_loads_built_effect_with_effectcraft_abi(self):
        if not importlib.util.find_spec('wasmtime'):
            self.skipTest('Wasmtime optional')
        self.render_reference(self.invert)
        convert_aex(self.source, self.output, reference_dir=self.references)
        import wasmtime
        engine = wasmtime.Engine()
        module = wasmtime.Module(engine, self.output.read_bytes())
        self.assertEqual(module.imports, [])
        self.assertIn('ec_render', [export.name for export in module.exports])

    def test_rejects_blur_alpha_and_no_op_instead_of_shipping_a_fake_effect(self):
        cases = (
            ('spatial blur', lambda img: img.filter(self.ImageFilter.GaussianBlur(5)),
             'Reference mismatch'),
            ('no effect', lambda img: img, 'no measurable change'),
            ('alpha effect', lambda img: img.putalpha(127) or img, 'transparency'),
        )
        for name, operation, warning in cases:
            with self.subTest(name=name):
                self.render_reference(operation)
                with self.assertRaises(UnsupportedAexError) as error:
                    convert_aex(self.source, self.output, reference_dir=self.references)
                self.assertFalse(self.output.exists())
                text = error.exception.report.read_text(encoding='utf-8')
                self.assertIn(warning, text)
                self.assertIn('WASM не создан', text)
                error.exception.report.unlink()

    def test_refuses_scaled_or_modified_charts_and_output_collisions(self):
        self.render_reference(self.invert)
        wrong = self.Image.new('RGB', (5, 5), (20, 40, 60))
        wrong.save(self.references / CHECK_AFTER)
        with self.assertRaisesRegex(ReferenceError, 'unscaled'):
            fit(self.references, self.digest)
        self.render_reference(self.invert)
        self.Image.new('RGBA', (852, 840), (0, 0, 0, 255)).save(self.references / TRAIN_INPUT)
        with self.assertRaisesRegex(ReferenceError, 'Input charts were changed'):
            fit(self.references, self.digest)
        prepare_charts(self.directory / 'another', aex_digest=self.digest)
        self.render_reference(self.invert)
        conflict = self.directory / 'Trained_aex_analysis.md'
        conflict.write_text('personal notes')
        with self.assertRaises(FileExistsError):
            convert_aex(self.source, self.output, reference_dir=self.references)
        self.assertEqual(conflict.read_text(), 'personal notes')

    def test_references_cannot_be_reused_with_a_different_aex_binary(self):
        self.render_reference(self.invert)
        marker = self.references / REFERENCE_METADATA
        metadata = json.loads(marker.read_text(encoding='utf-8'))
        metadata['aex_sha256'] = '0' * 64
        marker.write_text(json.dumps(metadata), encoding='utf-8')
        with self.assertRaisesRegex(ReferenceError, 'another .aex build'):
            convert_aex(self.source, self.output, reference_dir=self.references)
        self.assertFalse(self.output.exists())

    def test_rejects_sparse_alpha_changes_in_training_or_check_image(self):
        self.render_reference(self.invert)
        for filename, position in ((TRAIN_AFTER, (0, 0)), (CHECK_AFTER, (15, 15))):
            with self.subTest(filename=filename):
                path = self.references / filename
                with self.Image.open(path) as image:
                    image = image.convert('RGBA')
                    image.putpixel(position, (*image.getpixel(position)[:3], 250))
                    image.save(path)
                with self.assertRaises(UnsupportedAexError) as error:
                    convert_aex(self.source, self.output, reference_dir=self.references)
                self.assertIn('transparency', error.exception.report.read_text(encoding='utf-8'))
                self.assertFalse(self.output.exists())
                error.exception.report.unlink()
                self.render_reference(self.invert)

    def test_template_integrity_and_no_untrusted_manifest_or_binary_code(self):
        self.assertEqual(hashlib.sha256(WASM).hexdigest(), WASM_SHA256)
        self.assertEqual(MANIFEST, json.loads((ROOT / 'effectcraft_plugins/measured_color_lut_manifest.json')
                                              .read_text(encoding='utf-8')))
        self.assertEqual(WASM.count(manifest_bytes(MANIFEST)), 1)
        self.assertEqual(WASM.count(SLOT_PREFIX + identity_lut() + SLOT_SUFFIX), 1)
        self.assertEqual(len(patch_wasm(WASM, MANIFEST, MANIFEST, identity_lut())), len(WASM))
        with self.assertRaisesRegex(RuntimeError, 'layout'):
            patch_wasm(b'\0asm' + bytes(100), MANIFEST, MANIFEST, identity_lut())
        with self.assertRaisesRegex(ValueError, '17\^3'):
            patch_wasm(WASM, MANIFEST, MANIFEST, b'bad')


if __name__ == '__main__':
    unittest.main()
