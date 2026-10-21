"""A parameter-fitted procedural family, not an archive of generator PNGs."""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from converters.aex_to_effectcraft import UnsupportedAexError, convert_aex, inspect_aex, main
from craft_converter.beam_layout import (SIGMAS, SLOT_PREFIX, SLOT_SUFFIX,
                                         TEMPLATE_WEIGHTS, patch_wasm, weight_bytes)
from craft_converter.effectcraft_measured_beam import MANIFEST, WASM
from craft_converter.measured_beam import Geometry, fit, render_pixel
from craft_converter.measured_port import (CHECK_AFTER, CHECK_INPUT, TRAIN_AFTER,
                                           TRAIN_INPUT, prepare_charts)
from test_aex_to_effectcraft import sample_aex, sample_with_pipl

ROOT = Path(__file__).resolve().parents[1]
PIL_AVAILABLE = importlib.util.find_spec('PIL') is not None


@unittest.skipUnless(PIL_AVAILABLE, 'Pillow from config/requirements.txt is needed')
class BeamPortTests(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        self.Image = Image
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.source = self.folder / 'UnknownLight.aex'
        raw = sample_aex().replace(b'GG AEPixelSorter2', b'XX AEPixelSorter2')
        self.source.write_bytes(sample_with_pipl(raw, 'Test beam', 'Generate', 'vendor.beam'))
        self.digest = inspect_aex(self.source).sha256
        self.refs = self.folder / 'refs'
        prepare_charts(self.refs, aex_digest=self.digest)
        self.output = self.folder / 'Line.wasm'
        self.geometry = Geometry((.5, .15), (.5, .85), 3, (252, 254, 255))
        self.weights = ((3.4, 34.5, 12.5, 10.3, 5.6),
                        (19.5, 82.7, 55.3, 46.1, 32.2),
                        (109.0, 4.6, 104.6, 98.1, 69.7))

    def generate_examples(self, *, check_geometry=None):
        for input_name, result_name in ((TRAIN_INPUT, TRAIN_AFTER), (CHECK_INPUT, CHECK_AFTER)):
            with self.Image.open(self.refs / input_name) as src:
                width, height = src.size
            geom = (check_geometry if input_name == CHECK_INPUT and check_geometry else self.geometry)
            rows = []
            for y in range(height):
                rows.extend(render_pixel(width, height, x, y, geom, self.weights) + (255,)
                            for x in range(width))
            result = self.Image.new('RGBA', (width, height))
            result.putdata(rows)
            result.save(self.refs / result_name, 'PNG')

    def test_two_sizes_fit_a_new_opaque_generator_without_copying_frames(self):
        self.generate_examples()
        fitted = fit(self.refs, self.digest)
        self.assertTrue(fitted.accepted, fitted.reason)
        self.assertLess(fitted.check_mae, 6)
        self.assertLessEqual(fitted.check_p95, 18)
        report = convert_aex(self.source, self.output, reference_dir=self.refs,
                             reference_model='line', language='en')
        text = report.read_text(encoding='utf-8')
        self.assertIn('NOT Saber', text)
        self.assertIn('another background', text)
        self.assertIn('Start', json.dumps(MANIFEST))
        wasm = self.output.read_bytes()
        self.assertTrue(wasm.startswith(b'\0asm'))
        self.assertNotEqual(wasm, WASM)
        self.assertLess(len(wasm), 16_000)  # Fifteen coefficients, not a captured image.
        self.assertNotIn(b'\x89PNG', wasm)
        self.assertIn(SLOT_PREFIX + weight_bytes(fitted.weights) + SLOT_SUFFIX, wasm)
        self.assertEqual(WASM.count(SLOT_PREFIX + TEMPLATE_WEIGHTS + SLOT_SUFFIX), 1)
        self.assertEqual(len(patch_wasm(WASM, MANIFEST, MANIFEST, TEMPLATE_WEIGHTS)), len(WASM))
        self.assertEqual(len(SIGMAS), 5)
        if shutil.which('node'):
            subprocess.run(['node', str(ROOT / 'tests/measured_beam_wasm_smoke.cjs'),
                            str(self.output)], check=True, capture_output=True)
        if importlib.util.find_spec('wasmtime'):
            import wasmtime
            module = wasmtime.Module(wasmtime.Engine(), wasm)
            self.assertEqual(module.imports, [])

    def test_rejects_an_unrelated_flat_generator_without_fake_wasm(self):
        for name in (TRAIN_AFTER, CHECK_AFTER):
            with self.Image.open(self.refs / (TRAIN_INPUT if name == TRAIN_AFTER else CHECK_INPUT)) as inp:
                self.Image.new('RGB', inp.size, (8, 32, 90)).save(self.refs / name)
        with self.assertRaises(UnsupportedAexError) as error:
            convert_aex(self.source, self.output, reference_dir=self.refs,
                        reference_model='line')
        self.assertIn('Модель луча отклонена', error.exception.report.read_text(encoding='utf-8'))
        self.assertFalse(self.output.exists())

    def test_rejects_moved_core_between_training_and_check(self):
        self.generate_examples(check_geometry=Geometry((.25, .15), (.25, .85), 3,
                                                        (252, 254, 255)))
        with self.assertRaises(UnsupportedAexError) as error:
            convert_aex(self.source, self.output, reference_dir=self.refs,
                        reference_model='line')
        self.assertIn('geometry/width changed', error.exception.report.read_text(encoding='utf-8'))
        self.assertFalse(self.output.exists())

    def test_rejects_alpha_and_requires_explicit_reference_mode(self):
        with self.assertRaisesRegex(ValueError, 'requires --reference-dir'):
            convert_aex(self.source, self.output, reference_model='line')
        self.generate_examples()
        with self.Image.open(self.refs / CHECK_AFTER) as image:
            image = image.copy()
            image.putalpha(100)
            image.save(self.refs / CHECK_AFTER)
        with self.assertRaises(UnsupportedAexError) as error:
            convert_aex(self.source, self.output, reference_model='line', reference_dir=self.refs)
        self.assertIn('Transparent output', error.exception.report.read_text(encoding='utf-8'))
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
