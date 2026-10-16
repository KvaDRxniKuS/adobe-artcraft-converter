"""File detection and mixed-queue routing without a Qt runtime."""
import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from project_import import (FC_TO_PR, PR_TO_FC, ProjectTypeError,
                            convert_queued_project, detect_project_direction,
                            next_output_path)
from test_reverse_writer import REFERENCE, SHELL, graphic_text_clip


class ProjectImportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.premiere = self.base / 'sample.prproj'
        self.filmcraft = self.base / 'sample.fcproj'
        self.shell = self.base / 'empty.prproj'
        self.output_dir = self.base / 'converted'
        self.premiere.write_text(REFERENCE, encoding='utf-8')
        self.shell.write_text(SHELL, encoding='utf-8')
        self.filmcraft.write_text(json.dumps({
            'format': 'filmcraft.project',
            'project': {'items': {'1': {'name': 'Scene', 'kind': {
                'Sequence': {'video_tracks': [], 'audio_tracks': []},
            }}}},
        }), encoding='utf-8')

    def test_detects_projects_by_content_not_filename(self):
        self.assertEqual(detect_project_direction(self.premiere), PR_TO_FC)
        self.assertEqual(detect_project_direction(self.filmcraft), FC_TO_PR)
        renamed_json = self.base / 'renamed.prproj'
        renamed_json.write_bytes(self.filmcraft.read_bytes())
        self.assertEqual(detect_project_direction(renamed_json), FC_TO_PR)
        renamed_xml = self.base / 'renamed.fcproj'
        renamed_xml.write_bytes(self.premiere.read_bytes())
        self.assertEqual(detect_project_direction(renamed_xml), PR_TO_FC)

    def test_accepts_legacy_premiere_xml_gzip_and_filmcraft_json(self):
        xml = self.base / 'legacy.prproj.txt'
        xml.write_text(REFERENCE, encoding='utf-8')
        compressed = self.base / 'compressed.prproj'
        compressed.write_bytes(gzip.compress(REFERENCE.encode('utf-8')))
        json_path = self.base / 'filmcraft.json'
        json_path.write_bytes(self.filmcraft.read_bytes())
        utf16 = self.base / 'utf16.prproj'
        utf16.write_bytes(REFERENCE.encode('utf-16-le'))
        self.assertEqual(detect_project_direction(xml), PR_TO_FC)
        self.assertEqual(detect_project_direction(compressed), PR_TO_FC)
        self.assertEqual(detect_project_direction(utf16), PR_TO_FC)
        self.assertEqual(detect_project_direction(json_path), FC_TO_PR)

    def test_rejects_shortcuts_and_unrecognized_files(self):
        shortcuts = self.base / 'profile.json'
        shortcuts.write_text('{"format":"filmcraft-keyboard-shortcuts"}', encoding='utf-8')
        with self.assertRaises(ProjectTypeError) as raised:
            detect_project_direction(shortcuts)
        self.assertEqual(raised.exception.code, 'shortcut')
        kys = self.base / 'profile.kys'
        kys.write_text('<KeyboardShortcuts/>', encoding='utf-8')
        with self.assertRaises(ProjectTypeError) as raised:
            detect_project_direction(kys)
        self.assertEqual(raised.exception.code, 'shortcut')
        bad_xml = self.base / 'not_premiere.xml'
        bad_xml.write_text('<KeyboardShortcuts/>', encoding='utf-8')
        with self.assertRaises(ProjectTypeError) as raised:
            detect_project_direction(bad_xml)
        self.assertEqual(raised.exception.code, 'shortcut')
        missing = self.base / 'missing.fcproj'
        with self.assertRaises(ProjectTypeError) as raised:
            detect_project_direction(missing)
        self.assertEqual(raised.exception.code, 'missing')

    def test_output_names_do_not_replace_projects_or_reports(self):
        self.output_dir.mkdir()
        (self.output_dir / 'sample.prproj').write_text('existing', encoding='utf-8')
        (self.output_dir / 'sample_2_conversion_report.md').write_text('report', encoding='utf-8')
        self.assertEqual(next_output_path(self.output_dir, 'sample', '.prproj'),
                         self.output_dir / 'sample_3.prproj')

    def test_reverse_job_in_the_shared_queue_creates_project_and_report(self):
        record = {'path': str(self.filmcraft), 'direction': FC_TO_PR}
        output, messages = convert_queued_project(record, self.output_dir, 'en')
        self.assertEqual(output.suffix, '.prproj')
        self.assertTrue(output.read_bytes().startswith(b'\x1f\x8b'))
        self.assertGreater(messages, 0)
        report = output.with_name(output.stem + '_conversion_report.md')
        self.assertIn('FilmCraft → Premiere', report.read_text(encoding='utf-8'))
        self.assertNotIn('Reference:', report.read_text(encoding='utf-8'))
        second_output, _ = convert_queued_project(record, self.output_dir, 'en')
        self.assertNotEqual(output, second_output)
        self.assertEqual(self.premiere.read_text(encoding='utf-8'), REFERENCE)
        self.assertEqual(self.shell.read_text(encoding='utf-8'), SHELL)

    def test_fc_graphic_in_txt_input_generates_png_in_queue_output(self):
        try:
            from PIL import Image  # noqa: F401 - import checks the installed runtime dependency
        except ImportError:
            self.skipTest('Pillow is not installed')
        project = json.loads(self.filmcraft.read_text(encoding='utf-8'))
        project['project']['items']['314'] = {'id': 314, 'kind': {
            'Graphic': {'width': 320, 'height': 180, 'rate': {'num': 25, 'den': 1}},
        }}
        sequence = project['project']['items']['1']['kind']['Sequence']
        sequence['video_tracks'] = [{'items': [graphic_text_clip(315, 'Пример', 0)]}]
        source = self.base / 'graphic.fcproj.txt'
        source.write_text(json.dumps(project), encoding='utf-8')
        self.assertEqual(detect_project_direction(source), FC_TO_PR)
        output, _ = convert_queued_project({'path': str(source), 'direction': FC_TO_PR},
                                           self.output_dir)
        self.assertTrue(output.is_file())
        self.assertEqual(len(list(self.output_dir.glob('*_graphic_*.png'))), 1)
        report = output.with_name(output.stem + '_conversion_report.md')
        self.assertIn('растровый PNG', report.read_text(encoding='utf-8'))
        self.assertEqual(json.loads(source.read_text(encoding='utf-8')), project)

    def test_optional_missing_shell_rejected_without_touching_fc(self):
        with self.assertRaisesRegex(ValueError, 'оболочка'):
            convert_queued_project({'path': str(self.filmcraft), 'direction': FC_TO_PR,
                                    'shell': str(self.base / 'absent.prproj')},
                                   self.output_dir)
        self.assertEqual(detect_project_direction(self.filmcraft), FC_TO_PR)

    def test_forward_job_routes_to_existing_converter(self):
        def convert(path):
            path.write_text('{"format":"filmcraft.project"}', encoding='utf-8')
            return {'project': {'items': {'1': {'kind': {'Sequence': {
                'video_tracks': [{'items': [{}], 'transitions': []}],
                'audio_tracks': [],
            }}}}}}

        with patch('project_import.Converter') as converter_type:
            converter_type.return_value.convert.side_effect = convert
            converter_type.return_value.warnings = ['review effect']
            output, messages = convert_queued_project(
                {'path': str(self.premiere), 'direction': PR_TO_FC},
                self.output_dir, 'en')
            converter_type.assert_called_once_with(self.premiere, language='en')
        self.assertEqual(messages, 1)
        self.assertEqual(output.suffix, '.fcproj')
        self.assertEqual(json.loads(output.read_text(encoding='utf-8'))['format'],
                         'filmcraft.project')
        report = output.with_name(output.stem + '_conversion_report.md')
        self.assertIn('Timeline clips: 1', report.read_text(encoding='utf-8'))
        self.assertIn('review effect', report.read_text(encoding='utf-8'))
        self.assertFalse(list(self.output_dir.glob('*.tmp')))

    def test_changed_type_after_import_is_not_converted_using_old_direction(self):
        self.filmcraft.write_text(REFERENCE, encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Формат проекта изменился'):
            convert_queued_project({'path': str(self.filmcraft), 'direction': FC_TO_PR},
                                   self.output_dir)
        self.assertFalse(self.output_dir.exists())


if __name__ == '__main__':
    unittest.main()
