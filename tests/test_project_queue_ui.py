"""Headless UI checks; skipped when the host lacks system Qt libraries."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    from PySide6.QtWidgets import QApplication, QMessageBox
    import desktop_app
except (ImportError, OSError) as exc:
    desktop_app = None
    QT_ERROR = str(exc)
else:
    QT_ERROR = ''

from project_import import FC_TO_PR, PR_TO_FC
from test_reverse_writer import REFERENCE, SHELL


@unittest.skipUnless(desktop_app is not None, f'PySide6 GUI unavailable: {QT_ERROR}')
class MixedQueueUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        base = Path(self.directory.name)
        self.source = base / 'scene.fcproj'
        self.premiere = base / 'reference.prproj'
        self.shell = base / 'shell.prproj'
        self.output_dir = base / 'output'
        self.source.write_text(json.dumps({
            'format': 'filmcraft.project',
            'project': {'items': {'1': {
                'name': 'Scene',
                'kind': {'Sequence': {'video_tracks': [], 'audio_tracks': []}},
            }}},
        }), encoding='utf-8')
        self.premiere.write_text(REFERENCE, encoding='utf-8')
        self.shell.write_text(SHELL, encoding='utf-8')
        self.window = desktop_app.MainWindow()
        self.addCleanup(self.window.close)
        self.window.output_edit.setText(str(self.output_dir))

    def tearDown(self):
        if self.window.worker is not None:
            self.window.worker.wait(5000)
            self.app.processEvents()

    def test_one_queue_detects_both_directions_and_keeps_shortcuts_separate(self):
        self.assertEqual(self.window.table.columnCount(), 4)
        self.assertFalse(hasattr(self.window, 'reverse_btn'))
        self.assertIn('.fcproj', self.window.drop.title_label.text())
        self.window.add_paths([str(self.premiere), str(self.source)])
        self.assertEqual([r['direction'] for r in self.window.files], [PR_TO_FC, FC_TO_PR])
        self.assertFalse(self.window.reverse_panel.isHidden())
        self.assertEqual(self.window.table.currentRow(), 1)
        self.assertIn('FC → PR', self.window.table.item(1, 1).text())
        self.assertNotIn('reference', self.window.files[1])
        self.assertFalse(hasattr(self.window, 'reference_edit'))
        self.assertEqual(self.window.files[1]['state'], 'pending')
        self.assertNotIn('template', self.window.table.item(1, 2).text().lower())

        shortcuts = self.source.with_name('shortcuts.json')
        shortcuts.write_text('{"format":"filmcraft-keyboard-shortcuts"}', encoding='utf-8')
        with patch.object(QMessageBox, 'warning') as warning:
            self.window.add_paths([str(shortcuts)])
            self.assertIn(shortcuts.name, warning.call_args.args[2])
        self.assertEqual(len(self.window.files), 2)

    def test_optional_shell_belongs_to_selected_fc_item(self):
        second = self.source.with_name('another.fcproj')
        second.write_bytes(self.source.read_bytes())
        self.window.add_paths([str(self.source), str(second)])
        self.window.table.setCurrentCell(0, 0)
        self.window.shell_edit.setText(str(self.shell))
        self.window.table.setCurrentCell(1, 0)
        self.assertEqual(self.window.shell_edit.text(), '')
        self.window.language_combo.setCurrentIndex(1)
        self.assertEqual(self.window.files[0]['shell'], str(self.shell))
        self.window.table.setCurrentCell(0, 0)
        self.assertEqual(self.window.shell_edit.text(), str(self.shell))

    def test_no_shell_required_and_no_extra_window(self):
        self.window.add_paths([str(self.premiere), str(self.source)])
        calls = []

        def convert(record, output_dir, language):
            calls.append(record['direction'])
            output_dir.mkdir(exist_ok=True)
            output = output_dir / (str(len(calls)) + '.prproj')
            output.write_text('<PremiereData/>', encoding='utf-8')
            return output, 0

        with patch('desktop_app.convert_queued_project', side_effect=convert), \
             patch.object(QMessageBox, 'warning') as warning:
            self.window.start_queue()
            self.assertTrue(self.window.worker.wait(5000))
            self.app.processEvents()
            warning.assert_not_called()
        self.assertEqual(calls, [PR_TO_FC, FC_TO_PR])
        self.assertEqual([r['state'] for r in self.window.files], ['done', 'done'])

    def test_invalid_optional_shell_does_not_block_pr_job(self):
        self.window.add_paths([str(self.premiere), str(self.source)])
        self.window.shell_edit.setText(str(self.shell.with_name('missing.prproj')))

        def convert(record, output_dir, language):
            self.assertEqual(record['direction'], PR_TO_FC)
            output_dir.mkdir(exist_ok=True)
            destination = output_dir / 'reference.fcproj'
            destination.write_text('{}', encoding='utf-8')
            return destination, 0

        with patch('desktop_app.convert_queued_project', side_effect=convert), \
             patch.object(QMessageBox, 'warning') as warning:
            self.window.start_queue()
            warning.assert_called_once()
            self.assertTrue(self.window.worker.wait(5000))
            self.app.processEvents()
        self.assertEqual([r['state'] for r in self.window.files], ['done', 'error'])
        self.assertTrue(Path(self.window.files[0]['output']).is_file())

    def test_fc_project_converts_without_any_premiere_input(self):
        self.window.add_paths([str(self.source)])
        with patch.object(QMessageBox, 'critical') as critical, \
             patch.object(QMessageBox, 'warning') as warning:
            self.window.start_queue()
            self.assertTrue(self.window.busy)
            self.assertTrue(self.window.worker.wait(5000))
            self.app.processEvents()
            critical.assert_not_called()
            warning.assert_not_called()
        self.assertFalse(self.window.busy)
        self.assertEqual(self.window.files[0]['state'], 'done')
        output = Path(self.window.files[0]['output'])
        self.assertEqual(output.suffix, '.prproj')
        self.assertTrue(output.is_file())
        self.assertTrue(output.with_name(output.stem + '_conversion_report.md').is_file())


if __name__ == '__main__':
    unittest.main()
