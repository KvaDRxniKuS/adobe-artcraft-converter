"""Synthetic graph tests; they do not prove Premiere can open generated projects."""
import json
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from fcproj_to_prproj import NativeWriter, same_file
from reverse_project import (ReportWriteError, convert_reverse_project,
                             reverse_report_path)


REFERENCE = '''<PremiereData>
<MZ.BuildVersion.Created>old</MZ.BuildVersion.Created>
<MZ.BuildVersion.Modified>old</MZ.BuildVersion.Modified>
<MZ.Project.GUID>old-guid</MZ.Project.GUID>
<Sequence ObjectUID="sequence-1">
  <Name>Scene</Name>
  <TrackGroups><TrackGroup><Second ObjectRef="group-1" /></TrackGroup></TrackGroups>
</Sequence>
<VideoTrackGroup ObjectID="group-1">
  <FrameRect>0,0,1920,1080</FrameRect>
  <TrackGroup><FrameRate>10160640000</FrameRate><Tracks /></TrackGroup>
</VideoTrackGroup>
</PremiereData>'''
SHELL = '''<PremiereData>
<MZ.BuildVersion.Created>new-build</MZ.BuildVersion.Created>
<MZ.BuildVersion.Modified>new-build</MZ.BuildVersion.Modified>
</PremiereData>'''


class ReverseWriterTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.source = self.base / 'source.fcproj'
        self.reference = self.base / 'reference.prproj'
        self.shell = self.base / 'shell.prproj'
        self.output = self.base / 'result.prproj'
        self.source.write_text(json.dumps({
            'format': 'filmcraft.project',
            'project': {'items': {'1': {
                'name': 'Scene',
                'kind': {'Sequence': {
                    'settings': {
                        'width': 1920, 'height': 1080,
                        'frame_rate': {'num': 25, 'den': 1},
                    },
                    'video_tracks': [], 'audio_tracks': [],
                }},
            }}},
        }), encoding='utf-8')
        self.reference.write_text(REFERENCE, encoding='utf-8')
        self.shell.write_text(SHELL, encoding='utf-8')

    def writer(self):
        return NativeWriter(self.source, self.reference, self.shell)

    def test_writes_separate_project_using_shell_metadata(self):
        warnings = self.writer().write(self.output)
        root = ET.parse(self.output).getroot()
        self.assertEqual(root.findtext('MZ.BuildVersion.Created'), 'new-build')
        self.assertNotEqual(root.findtext('MZ.Project.GUID'), 'old-guid')
        self.assertIn('Обновлено существующих clip instances: 0', warnings[0])
        self.assertEqual(self.reference.read_text(encoding='utf-8'), REFERENCE)
        self.assertEqual(self.shell.read_text(encoding='utf-8'), SHELL)
        self.assertFalse(list(self.base.glob('*.tmp')))

    def test_mismatch_does_not_replace_existing_output(self):
        data = json.loads(self.source.read_text(encoding='utf-8'))
        data['project']['items']['1']['name'] = 'Different scene'
        self.source.write_text(json.dumps(data), encoding='utf-8')
        self.output.write_text('keep this version', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'отсутствует в Premiere-эталоне'):
            self.writer().write(self.output)
        self.assertEqual(self.output.read_text(encoding='utf-8'), 'keep this version')

    def test_writer_never_overwrites_any_input(self):
        for target in (self.source, self.reference, self.shell):
            before = target.read_bytes()
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, 'не должен совпадать'):
                self.writer().write(target)
            self.assertEqual(target.read_bytes(), before)

    def test_symlink_and_hardlink_to_template_are_rejected(self):
        symlink = self.base / 'linked.prproj'
        try:
            symlink.symlink_to(self.reference)
        except OSError:
            # Creating symlinks on Windows can require developer mode/admin.
            pass
        else:
            self.assertTrue(same_file(symlink, self.reference))
            with self.assertRaises(ValueError):
                self.writer().write(symlink)
            self.assertEqual(self.reference.read_text(encoding='utf-8'), REFERENCE)
        hardlink = self.base / 'hardlinked.prproj'
        os.link(self.reference, hardlink)
        self.assertTrue(same_file(hardlink, self.reference))
        with self.assertRaises(ValueError):
            self.writer().write(hardlink)

    def test_failed_serialization_preserves_existing_output(self):
        self.output.write_text('previous project', encoding='utf-8')
        writer = self.writer()

        def failing_write(file, **kwargs):
            file.write(b'incomplete')
            raise OSError('disk full')

        with patch.object(writer.tree, 'write', side_effect=failing_write):
            with self.assertRaisesRegex(OSError, 'disk full'):
                writer.write(self.output)
        self.assertEqual(self.output.read_text(encoding='utf-8'), 'previous project')
        self.assertFalse(list(self.base.glob('*.tmp')))

    def test_ui_workflow_writes_project_and_localized_report(self):
        report, messages = convert_reverse_project(
            self.source, self.reference, self.shell, self.output, 'en')
        self.assertEqual(report, reverse_report_path(self.output))
        self.assertGreater(len(messages), 0)
        text = report.read_text(encoding='utf-8')
        self.assertIn('# FilmCraft → Premiere conversion report', text)
        self.assertIn('Reference: `reference.prproj`', text)
        self.assertIn('Writer diagnostics below are currently in Russian', text)
        self.assertIn('Обновлено существующих clip instances: 0', text)
        self.assertTrue(self.output.is_file())
        self.assertEqual(self.reference.read_text(encoding='utf-8'), REFERENCE)

    def test_workflow_refuses_report_alias_to_template(self):
        report = reverse_report_path(self.output)
        report.symlink_to(self.reference)
        with self.assertRaisesRegex(ValueError, 'не может перезаписать'):
            convert_reverse_project(self.source, self.reference, self.shell, self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.reference.read_text(encoding='utf-8'), REFERENCE)

    def test_report_failure_keeps_existing_report_and_project_is_identified(self):
        report = reverse_report_path(self.output)
        report.write_text('previous report', encoding='utf-8')
        with patch('reverse_project.reverse_report_text', side_effect=OSError('report blocked')):
            with self.assertRaisesRegex(ReportWriteError, 'report blocked'):
                convert_reverse_project(self.source, self.reference, self.shell, self.output)
        self.assertTrue(self.output.is_file())
        self.assertEqual(report.read_text(encoding='utf-8'), 'previous report')
        self.assertFalse(list(self.base.glob('*.tmp')))


if __name__ == '__main__':
    unittest.main()
