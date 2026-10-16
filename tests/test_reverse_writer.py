"""Structural FC → PR checks; only Premiere Pro can verify actual compatibility."""
import contextlib
import gzip
import io
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from direct_fc_to_prproj import DirectWriter, GraphIndex
from fcproj_to_prproj import NativeWriter, TICKS, main as reverse_cli, same_file
from prproj_to_fcproj import Converter
from reverse_project import (ReportWriteError, convert_reverse_project,
                             reverse_report_path)

# Tiny hand-written project records for detection and legacy API tests only.
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


def fc_clip(clip_id, media_id, name, start=0, duration=2*TICKS, source_in=0, link=None):
    return {'id': clip_id, 'item': media_id, 'name': name, 'start': start,
            'duration': duration, 'source_in': source_in, 'speed': 1.0,
            'enabled': True, 'link': link, 'effects': [], 'markers': []}


def fc_track(kind, clips=None):
    return {'kind': kind, 'items': clips or [], 'transitions': [], 'effects': []}


def project_document(video_path: str, audio_path: str) -> dict:
    video = {
        'id': 1, 'name': 'Shot',
        'kind': {'Media': {'media': {'File': {'path': video_path}}, 'info': {
            'duration': 10 * TICKS, 'video': {
                'width': 1920, 'height': 1080,
                'frame_rate': {'num': 24, 'den': 1},
            }, 'audio_streams': [{'sample_rate': 48000, 'channels': 2}],
        }}},
    }
    audio = {
        'id': 2, 'name': 'Music',
        'kind': {'Media': {'media': {'File': {'path': audio_path}}, 'info': {
            'duration': 10 * TICKS, 'video': None,
            'audio_streams': [{'sample_rate': 48000, 'channels': 2}],
        }}},
    }
    main = {'id': 10, 'name': 'Main', 'kind': {'Sequence': {
        'settings': {'width': 1280, 'height': 720,
                     'frame_rate': {'num': 25, 'den': 1}, 'sample_rate': 48000},
        'video_tracks': [
            fc_track('Video', [fc_clip(11, 1, 'Shot A', 0, 2*TICKS, TICKS, link=7),
                               fc_clip(12, 1, 'Shot B', 3*TICKS, TICKS)]),
            fc_track('Video'), fc_track('Video'),
            fc_track('Video', [fc_clip(13, 1, 'Overlay', 4*TICKS, TICKS)]),
        ],
        'audio_tracks': [fc_track('Audio', [fc_clip(14, 2, 'Music A', 0, 2*TICKS,
                                                    link=7)]),
                         fc_track('Audio')],
    }}}
    second = {'id': 20, 'name': 'Second', 'kind': {'Sequence': {
        'settings': {'width': 1920, 'height': 1080,
                     'frame_rate': {'num': 30, 'den': 1}},
        'video_tracks': [fc_track('Video', [fc_clip(21, 1, 'Second shot', 0, TICKS)])],
        'audio_tracks': [],
    }}}
    return {'format': 'filmcraft.project', 'project': {
        'name': 'My FilmCraft Project',
        'items': {'1': video, '2': audio, '10': main, '20': second},
    }}


class DirectWriterTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.source = self.base / 'source.fcproj'
        self.video = self.base / 'shot.mp4'
        self.audio = self.base / 'music.wav'
        self.video.write_bytes(b'video fixture placeholder')
        self.audio.write_bytes(b'audio fixture placeholder')
        self.document = project_document(str(self.video), str(self.audio))
        self.save_fc()
        self.shell = self.base / 'empty.prproj'
        self.shell.write_text(SHELL, encoding='utf-8')
        self.output = self.base / 'result.prproj'

    def save_fc(self):
        self.source.write_text(json.dumps(self.document), encoding='utf-8')

    @staticmethod
    def read_root(path):
        return ET.fromstring(gzip.decompress(path.read_bytes()))

    def test_no_populated_reference_builds_multiple_sequences_media_tracks_clips(self):
        report, messages = convert_reverse_project(self.source, self.output, 'en')
        root = self.read_root(self.output)
        index = GraphIndex(root)
        self.assertEqual(root.tag, 'PremiereData')
        self.assertEqual(len(root.findall('Sequence')), 2)
        self.assertEqual(len(root.findall('Media')), 2)
        self.assertEqual(len(root.findall('VideoClipTrackItem')), 4)
        self.assertEqual(len(root.findall('AudioClipTrackItem')), 1)
        self.assertEqual(len(root.findall('./RootProjectItem/ProjectItemContainer/Items/Item')), 4)
        self.assertNotEqual(root.findtext('.//MZ.Project.GUID'),
                            '2bab6f0d-89fa-43ce-a237-646dbfa2c666')
        self.assertNotIn(b'seed-placeholder.mp4', gzip.decompress(self.output.read_bytes()))
        self.assertEqual(len(index.by_uid), len([node for node in root if node.get('ObjectUID')]))
        self.assertEqual(len(index.by_id), len([node for node in root if node.get('ObjectID')]))
        self.assertTrue(report.is_file())
        self.assertIn('without a populated Premiere reference', report.read_text(encoding='utf-8'))
        self.assertTrue(any('без заполненного эталона' in m for m in messages))
        self.assertEqual(self.source.read_text(encoding='utf-8'), json.dumps(self.document))

        # Independent reader verifies IDs, placements and media paths, not Adobe UI.
        roundtrip = Converter(self.output).convert(self.base / 'roundtrip.fcproj')
        items = list(roundtrip['project']['items'].values())
        media = [m for m in items if 'Media' in m.get('kind', {})]
        self.assertEqual({m['kind']['Media']['media']['File']['path'] for m in media},
                         {str(self.video), str(self.audio)})
        music = next(m for m in media if m['name'] == 'Music')
        self.assertIsNone(music['kind']['Media']['info']['video'])
        seq = {m['name']: m['kind']['Sequence'] for m in items
               if 'Sequence' in m.get('kind', {})}
        self.assertEqual(set(seq), {'Main', 'Second'})
        self.assertEqual(len(seq['Main']['video_tracks']), 4)
        self.assertEqual(len(seq['Main']['audio_tracks']), 2)
        self.assertEqual(seq['Main']['settings']['frame_rate'], {'num': 25, 'den': 1})
        video_clips = seq['Main']['video_tracks'][0]['items']
        self.assertEqual([(c['name'], c['start'], c['duration'], c['source_in'])
                          for c in video_clips],
                         [('Shot A', 0, 2*TICKS, TICKS), ('Shot B', 3*TICKS, TICKS, 0)])
        self.assertEqual(video_clips[0]['link'],
                         seq['Main']['audio_tracks'][0]['items'][0]['link'])
        self.assertIsNotNone(video_clips[0]['link'])

    def test_nested_sequence_reference_has_no_dummy_source(self):
        nested = {'id': 31, 'name': 'Second',
                  'kind': {'Media': {'media': {'File': {'path': ''}}}}}
        self.document['project']['items']['31'] = nested
        self.document['project']['items']['10']['kind']['Sequence']['video_tracks'][0]['items'].append(
            fc_clip(32, 31, 'Second nested', 5*TICKS, TICKS))
        self.save_fc()
        DirectWriter(self.source).write(self.output)
        forward = Converter(self.output).convert(self.base / 'nested_roundtrip.fcproj')
        items = forward['project']['items']
        matching = [m for m in items.values() if 'Media' in m.get('kind', {})
                    and not m['kind']['Media']['media']['File'].get('path')]
        self.assertEqual(len(matching), 1)
        main = next(i['kind']['Sequence'] for i in items.values()
                    if i.get('name') == 'Main' and 'Sequence' in i.get('kind', {}))
        self.assertEqual(main['video_tracks'][0]['items'][-1]['name'], 'Second nested')
        self.assertNotIn('seed-placeholder.mp4', gzip.decompress(self.output.read_bytes()).decode())

    def test_relative_media_path_resolves_against_fc_project(self):
        media = self.document['project']['items']['1']['kind']['Media']
        media['media']['File']['path'] = self.video.name
        self.save_fc()
        DirectWriter(self.source).write(self.output)
        roundtrip = Converter(self.output).convert(self.base / 'relative.fcproj')
        paths = {item['kind']['Media']['media']['File']['path']
                 for item in roundtrip['project']['items'].values()
                 if 'Media' in item.get('kind', {})}
        self.assertIn(str(self.video), paths)

    def test_unicode_names_and_xml_special_characters_survive(self):
        self.document['project']['items']['10']['name'] = 'Сцена & тест'
        self.document['project']['items']['1']['name'] = 'Кадр <1>'
        self.save_fc()
        DirectWriter(self.source).write(self.output)
        returned = Converter(self.output).convert(self.base / 'unicode.fcproj')
        names = {x['name'] for x in returned['project']['items'].values()}
        self.assertIn('Сцена & тест', names)
        self.assertIn('Кадр <1>', names)

    def test_shell_optional_and_never_modified(self):
        before = self.shell.read_bytes()
        DirectWriter(self.source, self.shell).write(self.output)
        root = self.read_root(self.output)
        self.assertEqual(root.findtext('.//MZ.BuildVersion.Created'), 'new-build')
        self.assertEqual(self.shell.read_bytes(), before)
        self.assertNotEqual(root.findtext('.//MZ.Project.GUID'), 'old-guid')

    def test_gzipped_empty_shell_supplies_only_build_strings(self):
        shell = self.base / 'empty_gzip.prproj'
        shell.write_bytes(gzip.compress(SHELL.encode('utf-8')))
        DirectWriter(self.source, shell).write(self.output)
        root = self.read_root(self.output)
        self.assertEqual(root.findtext('.//MZ.BuildVersion.Created'), 'new-build')
        self.assertNotEqual(root.findtext('.//MZ.Project.GUID'), 'old-guid')
        self.assertEqual(len(root.findall('Media')), 2)

    def test_cli_needs_only_fc_and_output(self):
        with patch('sys.argv', ['fcproj_to_prproj.py', str(self.source), str(self.output)]), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(reverse_cli(), 0)
        self.assertEqual(len(self.read_root(self.output).findall('Sequence')), 2)
        self.assertTrue(reverse_report_path(self.output).is_file())

    def test_empty_sequence_needs_no_media_or_reference(self):
        self.document['project']['items'] = {
            '10': {'name': 'Empty', 'kind': {'Sequence': {
                'video_tracks': [], 'audio_tracks': [],
                'settings': {'width': 1440, 'height': 900,
                             'frame_rate': {'num': 24, 'den': 1}},
            }}}
        }
        self.save_fc()
        messages = DirectWriter(self.source).write(self.output)
        root = self.read_root(self.output)
        self.assertEqual([n.findtext('Name') for n in root.findall('Sequence')], ['Empty'])
        self.assertEqual(len(root.findall('Media')), 0)
        self.assertEqual(len(root.findall('./RootProjectItem/ProjectItemContainer/Items/Item')), 1)
        self.assertTrue(any('0 медиа-объектов' in x for x in messages))

    def test_unsupported_properties_are_reported_not_silently_dropped(self):
        video_track = self.document['project']['items']['10']['kind']['Sequence']['video_tracks'][0]
        video_track['transitions'] = [{'effect': {'effect': 'cross_dissolve'}}]
        video_track['items'][0]['effects'] = [{'effect': 'custom_magic', 'params': {}}]
        video_track['items'][0]['enabled'] = False
        self.save_fc()
        _, messages = convert_reverse_project(self.source, self.output)
        text = '\n'.join(messages)
        self.assertIn('переходы пока не перенесены', text)
        self.assertIn('изменённых параметров не перенесено', text)
        self.assertIn('отключённый клип', text)

    def test_clip_resolves_unique_declared_id_when_items_key_is_different(self):
        items = self.document['project']['items']
        items['asset-video'] = items.pop('1')
        items['asset-video']['id'] = 314
        for sequence in (items['10'], items['20']):
            for track in sequence['kind']['Sequence']['video_tracks']:
                for clip in track['items']:
                    if clip['item'] == 1:
                        clip['item'] = 314
        self.save_fc()
        warnings = DirectWriter(self.source).write(self.output)
        self.assertTrue(any('ID 314 найден' in message for message in warnings))
        converted = Converter(self.output).convert(self.base / 'declared_id.fcproj')
        clips = [clip for item in converted['project']['items'].values()
                 if 'Sequence' in item.get('kind', {})
                 for track in item['kind']['Sequence']['video_tracks']
                 for clip in track['items']]
        self.assertEqual(len(clips), 4)
        self.assertEqual(len(self.read_root(self.output).findall('Media')), 2)

    def test_nested_sequence_resolves_by_declared_id(self):
        items = self.document['project']['items']
        items['sequence-two'] = items.pop('20')
        items['sequence-two']['id'] = 314
        items['10']['kind']['Sequence']['video_tracks'][0]['items'].append(
            fc_clip(32, 314, 'Nested', 5*TICKS, TICKS))
        self.save_fc()
        DirectWriter(self.source).write(self.output)
        returned = Converter(self.output).convert(self.base / 'nested_by_id.fcproj')
        main = next(i['kind']['Sequence'] for i in returned['project']['items'].values()
                    if i.get('name') == 'Main' and 'Sequence' in i.get('kind', {}))
        self.assertEqual(main['video_tracks'][0]['items'][-1]['name'], 'Nested')
        self.assertEqual(len(self.read_root(self.output).findall('Sequence')), 2)

    def test_missing_or_unsupported_item_explains_which_clip_and_why(self):
        clip = self.document['project']['items']['10']['kind']['Sequence']['video_tracks'][0]['items'][0]
        clip['item'] = 314
        self.save_fc()
        with self.assertRaisesRegex(ValueError, 'Shot A.*314.*project.items'):
            DirectWriter(self.source).write(self.output)
        self.assertFalse(self.output.exists())

        self.document['project']['items']['314'] = {
            'id': 314, 'name': 'A title', 'kind': {'Generator': {}}}
        self.save_fc()
        with self.assertRaisesRegex(ValueError, 'Shot A.*314.*Generator'):
            DirectWriter(self.source).write(self.output)
        self.assertFalse(self.output.exists())

    def test_ambiguous_declared_ids_are_not_mapped_to_the_wrong_media(self):
        self.document['project']['items']['asset-one'] = {
            'id': 314, 'kind': {'Media': {'media': {'File': {'path': str(self.video)}}}}}
        self.document['project']['items']['asset-two'] = {
            'id': 314, 'kind': {'Media': {'media': {'File': {'path': str(self.audio)}}}}}
        clip = self.document['project']['items']['10']['kind']['Sequence']['video_tracks'][0]['items'][0]
        clip['item'] = 314
        self.save_fc()
        with self.assertRaisesRegex(ValueError, 'ID 314 неоднозначен'):
            DirectWriter(self.source).write(self.output)
        self.assertFalse(self.output.exists())

    def test_invalid_references_overlaps_and_cycles_do_not_replace_project(self):
        self.output.write_bytes(b'keep old output')
        clip = self.document['project']['items']['10']['kind']['Sequence']['video_tracks'][0]['items'][0]
        clip['item'] = 500
        self.save_fc()
        with self.assertRaisesRegex(ValueError, 'отсутствующее медиа'):
            DirectWriter(self.source).write(self.output)
        self.assertEqual(self.output.read_bytes(), b'keep old output')

        clip['item'] = 1
        clip['duration'] = 5*TICKS
        self.save_fc()
        with self.assertRaisesRegex(ValueError, 'перекрываются'):
            DirectWriter(self.source).write(self.output)
        self.assertEqual(self.output.read_bytes(), b'keep old output')

        clip['duration'] = 2*TICKS
        clip['item'] = 20  # Main -> Second; make Second -> Main as well.
        second = self.document['project']['items']['20']['kind']['Sequence']['video_tracks'][0]['items'][0]
        second['item'] = 10
        self.save_fc()
        with self.assertRaisesRegex(ValueError, 'cyclic nested'):
            DirectWriter(self.source).write(self.output)
        self.assertEqual(self.output.read_bytes(), b'keep old output')

    def test_output_and_report_never_overwrite_inputs_or_shell(self):
        for target in (self.source, self.shell):
            before = target.read_bytes()
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, 'перезаписывать'):
                DirectWriter(self.source, self.shell).write(target)
            self.assertEqual(target.read_bytes(), before)
        report = reverse_report_path(self.output)
        report.symlink_to(self.shell)
        with self.assertRaisesRegex(ValueError, 'не может перезаписать'):
            convert_reverse_project(self.source, self.output, shell=self.shell)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.shell.read_bytes(), SHELL.encode())

    def test_invalid_xml_character_is_rejected_before_replacing_output(self):
        self.document['project']['items']['1']['name'] = 'bad\x00name'
        self.save_fc()
        self.output.write_bytes(b'keep old')
        with self.assertRaisesRegex(ValueError, 'Premiere XML некорректен'):
            DirectWriter(self.source).write(self.output)
        self.assertEqual(self.output.read_bytes(), b'keep old')

    def test_failed_serialization_preserves_existing_output(self):
        self.output.write_bytes(b'earlier version')
        with patch('direct_fc_to_prproj.os.replace', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError, 'disk full'):
                DirectWriter(self.source).write(self.output)
        self.assertEqual(self.output.read_bytes(), b'earlier version')
        self.assertFalse(list(self.base.glob('*.tmp')))

    def test_report_failure_identifies_saved_project_and_preserves_old_report(self):
        report = reverse_report_path(self.output)
        report.write_text('old report', encoding='utf-8')
        with patch('reverse_project.reverse_report_text', side_effect=OSError('report blocked')):
            with self.assertRaisesRegex(ReportWriteError, 'report blocked') as raised:
                convert_reverse_project(self.source, self.output)
        self.assertEqual(raised.exception.output, self.output)
        self.assertTrue(self.output.is_file())
        self.assertEqual(report.read_text(), 'old report')
        self.assertFalse(list(self.base.glob('*.tmp')))


class LegacyWriterTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.source = self.base / 'old.fcproj'
        self.reference = self.base / 'old.prproj'
        self.shell = self.base / 'shell.prproj'
        self.output = self.base / 'result.prproj'
        self.source.write_text(json.dumps({'format': 'filmcraft.project', 'project': {
            'items': {'1': {'name': 'Scene', 'kind': {'Sequence': {
                'settings': {'width': 1920, 'height': 1080,
                             'frame_rate': {'num': 25, 'den': 1}},
                'video_tracks': [], 'audio_tracks': [],
            }}}},
        }}), encoding='utf-8')
        self.reference.write_text(REFERENCE, encoding='utf-8')
        self.shell.write_text(SHELL, encoding='utf-8')

    def test_legacy_writer_does_not_overwrite_any_input(self):
        for target in (self.source, self.reference, self.shell):
            before = target.read_bytes()
            with self.subTest(target=target), self.assertRaises(ValueError):
                NativeWriter(self.source, self.reference, self.shell).write(target)
            self.assertEqual(target.read_bytes(), before)
        self.assertTrue(same_file(self.source, self.source))

    def test_legacy_writer_still_accepts_old_reference_when_used_directly(self):
        warnings = NativeWriter(self.source, self.reference, self.shell).write(self.output)
        self.assertIn('существующих clip instances', warnings[0])
        self.assertEqual(ET.parse(self.output).getroot().findtext('MZ.BuildVersion.Created'),
                         'new-build')


if __name__ == '__main__':
    unittest.main()
