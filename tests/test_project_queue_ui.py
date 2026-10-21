"""Headless UI checks; skipped when the host lacks system Qt libraries."""
import json
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    from PySide6.QtWidgets import QApplication, QMessageBox, QFrame
    import desktop_app
except (ImportError, OSError) as exc:
    desktop_app = None
    QT_ERROR = str(exc)
else:
    QT_ERROR = ''

from project_import import FC_TO_PR, PR_TO_FC
from test_reverse_writer import REFERENCE, SHELL
from test_aex_to_effectcraft import sample_aex, sample_deep_glow
from effectcraft_deep_glow import WASM as GLOW_WASM


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

    def test_every_subtab_uses_one_page_layout_with_source_target_and_footer(self):
        pages = [tabs.widget(index)
                 for tabs in (self.window.premiere_tabs, self.window.after_effects_tabs,
                              self.window.photoshop_tabs)
                 for index in range(3)]
        self.assertEqual(len(pages), 9)
        # The stylesheet belongs to QApplication, not only the first QMainWindow:
        # every nested QScrollArea and its cards must be styled on Windows too.
        self.assertIn('QFrame#panel', self.app.styleSheet())
        self.assertIn('QWidget#featureContent', self.app.styleSheet())
        for page in pages:
            with self.subTest(page=page.__class__.__name__):
                self.assertIsInstance(page, desktop_app.FeaturePage)
                self.assertTrue(page.widgetResizable())
                self.assertEqual(page.objectName(), 'featurePage')
                self.assertEqual(page.widget().objectName(), 'featureContent')
                self.assertIs(page.root.itemAt(0).widget(), page.title_label)
                self.assertIs(page.root.itemAt(1).widget(), page.note_label)
                self.assertIs(page.root.itemAt(2).widget(), page.source_panel)
                self.assertIs(page.root.itemAt(3).widget(), page.target_panel)
                self.assertIs(page.root.itemAt(4).layout(), page.details_layout)
                self.assertIs(page.root.itemAt(5).layout(), page.footer_layout)
                self.assertIs(page.root.itemAt(6).widget(), page.footnote_label)
                self.assertEqual(page.root.spacing(), 12)
                margins = page.root.contentsMargins()
                self.assertEqual((margins.left(), margins.top(),
                                  margins.right(), margins.bottom()), (18, 18, 18, 18))
                for card in (page.source_panel, page.target_panel):
                    self.assertEqual(card.objectName(), 'panel')
                    self.assertEqual(card.frameShape(), QFrame.StyledPanel)
                    card_margins = card.layout().contentsMargins()
                    self.assertEqual((card_margins.left(), card_margins.top(),
                                      card_margins.right(), card_margins.bottom()),
                                     (16, 12, 16, 12))
                self.assertTrue(page.title_label.text())
                self.assertTrue(page.note_label.text())
                self.assertTrue(page.source_title.text())
                self.assertTrue(page.target_title.text())
        self.assertIs(self.window.premiere_tabs.widget(0), self.window.project_page)
        self.assertIs(self.window.project_page.source_panel.findChild(desktop_app.DropArea),
                      self.window.drop)
        self.assertIs(self.window.project_page.details_layout.itemAt(0).widget().findChild(
            type(self.window.table)), self.window.table)
        self.assertIs(self.window.shortcut_panel.input_edit.parent(),
                      self.window.shortcut_panel.source_panel)
        self.assertIs(self.window.plugin_panel.output_edit.parent(),
                      self.window.plugin_panel.target_panel)
        self.assertIs(self.window.project_page.footer_layout.itemAt(2).widget(),
                      self.window.run_btn)
        self.assertIs(self.window.shortcut_panel.footer_layout.itemAt(1).widget(),
                      self.window.shortcut_panel.run_btn)
        self.assertIs(self.window.plugin_panel.footer_layout.itemAt(1).widget(),
                      self.window.plugin_panel.run_btn)

    def test_program_and_feature_tabs_preserve_state_on_language_switch(self):
        self.assertEqual(self.window.program_tabs.count(), 3)
        self.assertEqual([self.window.program_tabs.tabText(i) for i in range(3)], [
            'Premiere Pro ↔ FilmCraft', 'After Effects ↔ EffectCraft',
            'Photoshop ↔ PhotoCraft'])
        for tabs in (self.window.premiere_tabs, self.window.after_effects_tabs,
                     self.window.photoshop_tabs):
            self.assertEqual(tabs.count(), 3)
        self.assertIs(self.window.premiere_tabs.widget(0).findChild(desktop_app.DropArea),
                      self.window.drop)  # Real queue belongs to this page.
        self.assertEqual(self.window.after_effects_tabs.currentIndex(), 2)
        self.window.program_tabs.setCurrentIndex(1)
        self.window.after_effects_tabs.setCurrentIndex(0)
        planned = self.window.after_effects_tabs.currentWidget()
        self.assertIsInstance(planned, desktop_app.PlannedFeature)
        self.assertFalse(hasattr(planned, 'run_btn'))
        self.assertTrue(planned.title_label.text())
        self.assertIn('EffectCraft', planned.note_label.text())
        self.assertIn('PhotoCraft', self.window.photoshop_tabs.widget(0).note_label.text())
        self.window.plugin_panel.input_edit.setText('keep this path')
        self.window.language_combo.setCurrentIndex(1)
        self.assertEqual(self.window.program_tabs.currentIndex(), 1)
        self.assertEqual(self.window.after_effects_tabs.currentIndex(), 0)
        self.assertIn('Not implemented yet', planned.title_label.text())
        self.assertIn('planned', self.window.photoshop_tabs.tabText(0))
        self.assertIn('Not implemented yet', self.window.after_effects_tabs.tabToolTip(0))
        self.assertEqual(self.window.plugin_panel.input_edit.text(), 'keep this path')
        self.assertEqual(self.window.project_page.title_label.text(),
                         desktop_app.tr('en', 'project_heading'))
        self.assertEqual(self.window.project_page.source_title.text(),
                         desktop_app.tr('en', 'source_projects'))
        self.assertEqual(self.window.shortcut_panel.target_title.text(),
                         desktop_app.tr('en', 'target_shortcuts'))
        self.assertEqual(self.window.plugin_panel.source_title.text(),
                         desktop_app.tr('en', 'source_plugin'))
        self.assertEqual(planned.target_message.text(),
                         desktop_app.tr('en', 'planned_target'))

    def test_effectcraft_plugins_tab_stays_outside_project_queue_and_writes_wasm(self):
        from PySide6.QtWidgets import QFileDialog
        source = self.source.with_name('AEPixelSorter2.aex.txt')
        source.write_bytes(sample_aex())
        self.window.program_tabs.setCurrentIndex(1)
        self.window.after_effects_tabs.setCurrentIndex(2)
        panel = self.window.plugin_panel
        self.assertIs(self.window.after_effects_tabs.currentWidget(), panel)
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(source), '')):
            panel.choose_input()
        self.assertEqual(panel.input_edit.text(), str(source))
        output = Path(panel.output_edit.text())
        self.assertEqual(output.suffix, '.wasm')
        with patch.object(QMessageBox, 'information') as notice, \
             patch.object(QMessageBox, 'critical') as error:
            panel.convert()
            error.assert_not_called()
            notice.assert_called_once()
        self.assertEqual(output.read_bytes()[:4], b'\0asm')
        self.assertTrue(output.with_name(output.stem + '_conversion_report.md').exists())
        self.assertEqual(panel.status_label.text(),
                         desktop_app.tr(panel.language, 'done', name=output.name))
        self.assertEqual(self.window.files, [])  # Projects still use one shared queue.
        with patch.object(QMessageBox, 'critical') as error:
            panel.convert()
            error.assert_called_once()  # Never overwrite the existing WASM/report.

    def test_plugins_tab_exports_deep_glow_and_analyzes_other_aex_without_fake_wasm(self):
        panel = self.window.plugin_panel
        source = self.source.with_name('Deep Glow.aex.txt')
        source.write_bytes(sample_deep_glow())
        output = self.source.with_name('DeepGlow_effectcraft.wasm')
        panel.input_edit.setText(str(source))
        panel.output_edit.setText(str(output))
        with patch.object(QMessageBox, 'information') as info, \
             patch.object(QMessageBox, 'critical') as error:
            panel.convert()
            error.assert_not_called()
            info.assert_called_once()
        self.assertEqual(output.read_bytes(), GLOW_WASM)
        self.assertIn('Glow', info.call_args.args[2])
        self.assertTrue(output.with_name(output.stem + '_conversion_report.md').is_file())

        # A valid but unrelated DLL is accepted for analysis, not mislabelled
        # as either supported effect. A warning includes the diagnostic report.
        source.write_bytes(sample_aex().replace(b'GG AEPixelSorter2', b'ZZ AEPixelSorter2'))
        unknown = self.source.with_name('other_effect.wasm')
        panel.output_edit.setText(str(unknown))
        with patch.object(QMessageBox, 'warning') as warning, \
             patch.object(QMessageBox, 'information') as info, \
             patch.object(QMessageBox, 'critical') as error:
            panel.convert()
            warning.assert_called_once()
            info.assert_not_called()
            error.assert_not_called()
        self.assertIn('aex_analysis.md', warning.call_args.args[2])
        self.assertFalse(unknown.exists())
        self.assertTrue(unknown.with_name(unknown.stem + '_aex_analysis.md').is_file())
        self.assertEqual(self.window.files, [])

    def test_hotkeys_tab_converts_kys_and_json_without_extra_window(self):
        from PySide6.QtWidgets import QFileDialog
        template = Path(desktop_app.__file__).parent / 'Premiere_Shortcuts_Template.kys'
        keys = self.source.with_name('keys.kys')
        tree = ET.parse(template)
        item = next(x for x in tree.getroot().iter()
                    if x.findtext('commandname') == 'cmd.tools.01pointer')
        ET.SubElement(item, 'virtualkey').text = str(0x80000000 + ord('V'))
        ET.SubElement(item, 'modifier.ctrl').text = 'true'
        tree.write(keys, encoding='utf-8', xml_declaration=True)
        self.window.program_tabs.setCurrentIndex(0)
        self.window.premiere_tabs.setCurrentIndex(1)
        panel = self.window.shortcut_panel
        self.assertIs(self.window.premiere_tabs.currentWidget(), panel)
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(keys), '')):
            panel.choose_input()
        output = Path(panel.output_edit.text())
        self.assertEqual(output.suffix, '.json')
        with patch.object(QMessageBox, 'information') as notice, \
             patch.object(QMessageBox, 'critical') as error:
            panel.convert()
            error.assert_not_called()
            notice.assert_called_once()
        converted = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(converted['format'], 'filmcraft-keyboard-shortcuts')
        self.assertIn({'command': 'tool.selection', 'keys': 'Cmd+V'}, converted['bindings'])
        self.assertTrue(output.with_name(output.stem + '_shortcuts_report.md').exists())
        self.assertEqual(panel.status_label.text(),
                         desktop_app.tr(panel.language, 'done', name=output.name))
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(output), '')):
            panel.choose_input()
        self.assertEqual(Path(panel.output_edit.text()).suffix, '.kys')
        with patch.object(QMessageBox, 'information') as notice, \
             patch.object(QMessageBox, 'critical') as error:
            panel.convert()
            error.assert_not_called()
            notice.assert_called_once()
        self.assertTrue(Path(panel.output_edit.text()).read_bytes().startswith(b'<?xml'))
        self.assertEqual(self.window.files, [])

    def test_optional_shell_belongs_to_selected_fc_item(self):
        second = self.source.with_name('another.fcproj')
        second.write_bytes(self.source.read_bytes())
        self.window.add_paths([str(self.source), str(second)])
        self.window.table.setCurrentCell(0, 0)
        self.window.shell_edit.setText(str(self.shell))
        self.window.raster_checkbox.setChecked(True)
        self.window.table.setCurrentCell(1, 0)
        self.assertEqual(self.window.shell_edit.text(), '')
        self.assertFalse(self.window.raster_checkbox.isChecked())
        self.window.language_combo.setCurrentIndex(1)
        self.assertEqual(self.window.files[0]['shell'], str(self.shell))
        self.assertEqual(self.window.files[0]['graphic_mode'], 'png')
        self.window.table.setCurrentCell(0, 0)
        self.assertEqual(self.window.shell_edit.text(), str(self.shell))
        self.assertTrue(self.window.raster_checkbox.isChecked())

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
