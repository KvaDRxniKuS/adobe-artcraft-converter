#!/usr/bin/env python3
"""Best-effort native Premiere project writer from FilmCraft JSON.

This first writer uses a populated Premiere project as an object-graph template.
It is deliberately strict: it writes only when the FilmCraft sequences/tracks/clips
can be aligned to the template graph. It never emits FCP XML or fabricates a graph
that Premiere has not validated.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

TICKS = 254_016_000_000


def norm_path(value: str | None) -> str:
    if not value:
        return ''
    # Normalize Windows paths even when running on Linux/macOS.
    value = value.strip().replace('/', '\\')
    value = re.sub(r'\\+', r'\\', value)
    return value.casefold()


class NativeWriter:
    def __init__(self, fc_path: Path, reference_path: Path, shell_path: Path | None = None):
        self.fc_path = fc_path
        self.reference_path = reference_path
        self.shell_path = shell_path
        self.warnings: list[str] = []
        self.fc = json.loads(fc_path.read_text(encoding='utf-8-sig'))
        if self.fc.get('format') != 'filmcraft.project':
            raise ValueError('Входной JSON не является проектом FilmCraft (ожидается format=filmcraft.project).')
        self.project = self.fc.get('project') or {}
        self.items: dict[str, dict] = {str(k): v for k, v in (self.project.get('items') or {}).items()}
        self.tree = self._load_premiere(reference_path)
        self.root = self.tree.getroot()
        self.by_id = {e.get('ObjectID'): e for e in self.root.iter() if e.get('ObjectID')}
        self.by_uid = {e.get('ObjectUID'): e for e in self.root.iter() if e.get('ObjectUID')}
        self.sequence_by_name = {
            (e.findtext('Name') or '').strip(): e
            for e in self.root.iter('Sequence') if e.get('ObjectUID')
        }
        self.native_media_sources: dict[tuple[str, str, int], tuple[ET.Element, str | None]] = {}
        self._index_native_sources()

    @staticmethod
    def _load_premiere(path: Path) -> ET.ElementTree:
        data = path.read_bytes()
        if data[:2] == b'\x1f\x8b':
            import gzip, io
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
                data = stream.read(64 * 1024 * 1024 + 1)
        if len(data) > 64 * 1024 * 1024:
            raise ValueError('Premiere template exceeds 64 MiB safety limit.')
        if data.startswith((b'\xff\xfe', b'\xfe\xff')):
            data = data.decode('utf-16').encode('utf-8')
        elif not data.lstrip().startswith(b'<'):
            for enc in ('utf-8', 'utf-16-le', 'utf-16-be'):
                try:
                    decoded = data.decode(enc)
                    if '<PremiereData' in decoded:
                        data = decoded.encode('utf-8')
                        break
                except UnicodeError:
                    pass
        return ET.ElementTree(ET.fromstring(data))

    def resolve(self, ref: ET.Element | None) -> ET.Element | None:
        if ref is None:
            return None
        if ref.get('ObjectRef'):
            return self.by_id.get(ref.get('ObjectRef'))
        if ref.get('ObjectURef'):
            return self.by_uid.get(ref.get('ObjectURef'))
        return ref

    def _apply_blank_shell_metadata(self) -> None:
        if self.shell_path is None:
            self.warnings.append('Не задан Premiere blank shell; метаданные build/project shell оставлены от populated graph reference.')
            return
        shell_root = self._load_premiere(self.shell_path).getroot()
        for tag in ('MZ.BuildVersion.Created', 'MZ.BuildVersion.Modified'):
            source = shell_root.find('.//' + tag)
            target = self.root.find('.//' + tag)
            if source is not None and target is not None and source.text:
                target.text = source.text
        # Avoid reusing the blank template's project identity or the reference's ID.
        project_guid = self.root.find('.//MZ.Project.GUID')
        if project_guid is not None:
            project_guid.text = str(uuid.uuid4())

    def _clip_source_path(self, clip: ET.Element) -> str:
        inner = clip.find('Clip')
        source = self.resolve(inner.find('Source') if inner is not None else None)
        media_ref = source.find('.//Media') if source is not None else None
        media = self.resolve(media_ref)
        if media is None:
            return ''
        return norm_path(media.findtext('ActualMediaFilePath') or media.findtext('FilePath') or media.findtext('RelativePath'))

    def _index_native_sources(self) -> None:
        # Each source Clip object references a media source. The sample graph also
        # carries the audio SecondaryIndex on AudioClip; preserve that stream route.
        for tag, kind in (('VideoClip', 'video'), ('AudioClip', 'audio')):
            for clip in self.root.iter(tag):
                if not clip.get('ObjectID'):
                    continue
                path = self._clip_source_path(clip)
                if not path:
                    continue
                index = 0
                if kind == 'audio':
                    try:
                        index = max(0, int(clip.findtext('SecondaryIndex', '0') or 0))
                    except ValueError:
                        index = 0
                inner = clip.find('Clip')
                src = self.resolve(inner.find('Source') if inner is not None else None)
                if src is not None:
                    self.native_media_sources[(path, kind, index)] = (src, None)

    def _media_item(self, item_id) -> dict | None:
        return self.items.get(str(item_id))

    @staticmethod
    def _fc_media_path(item: dict | None) -> str:
        if not item:
            return ''
        media = item.get('kind', {}).get('Media', {}).get('media', {})
        path = (media.get('File') or {}).get('path')
        if not path:
            path = media.get('path') or media.get('url')
        return norm_path(path)

    def _fc_item_kind(self, clip: dict) -> str:
        source = self._media_item(clip.get('item'))
        if source and 'Sequence' in source.get('kind', {}):
            return 'sequence'
        # The current FilmCraft schema exports nested sequences as Media entries
        # with an empty File.path; identify them by the sequence name.
        if source and not self._fc_media_path(source) and source.get('name') in self.sequence_by_name:
            return 'sequence'
        return 'media'

    def _sequence_track_groups(self, seq: ET.Element) -> dict[str, ET.Element]:
        groups: dict[str, ET.Element] = {}
        group_list = seq.find('TrackGroups')
        if group_list is None:
            return groups
        for pair in group_list.findall('TrackGroup'):
            obj = self.resolve(pair.find('Second'))
            if obj is not None and obj.tag in ('VideoTrackGroup', 'AudioTrackGroup'):
                groups['video' if obj.tag == 'VideoTrackGroup' else 'audio'] = obj
        return groups

    def _native_tracks(self, group: ET.Element) -> list[ET.Element]:
        node = group.find('./TrackGroup/Tracks')
        if node is None:
            return []
        refs = sorted(node.findall('Track'), key=lambda e: int(e.get('Index', '0')))
        return [obj for obj in (self.resolve(ref) for ref in refs) if obj is not None]

    def _native_track_items(self, track: ET.Element) -> list[ET.Element]:
        container = track.find('./ClipTrack/ClipItems/TrackItems')
        if container is None:
            return []
        refs = sorted(container.findall('TrackItem'), key=lambda e: int(e.get('Index', '0')))
        return [obj for obj in (self.resolve(ref) for ref in refs) if obj is not None]

    def _fc_sequence_item(self, sequence_item: dict) -> dict:
        return sequence_item.get('kind', {}).get('Sequence', {})

    def _frame_rate_period(self, rate: dict | None) -> int | None:
        if not isinstance(rate, dict):
            return None
        try:
            num, den = int(rate['num']), int(rate['den'])
            return round(TICKS * den / num) if num > 0 and den > 0 else None
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            return None

    def _validate_settings(self, name: str, fc_seq: dict, native_groups: dict[str, ET.Element]) -> None:
        settings = fc_seq.get('settings', {})
        video = native_groups.get('video')
        if video is None:
            raise ValueError(f'Последовательность «{name}»: в шаблоне нет видеогруппы дорожек.')
        rect = (video.findtext('FrameRect') or '').split(',')
        if len(rect) >= 4:
            try:
                width, height = int(float(rect[2]) - float(rect[0])), int(float(rect[3]) - float(rect[1]))
                if settings.get('width') and settings.get('height') and (width, height) != (int(settings['width']), int(settings['height'])):
                    raise ValueError(f'«{name}»: размер последовательности FilmCraft {settings["width"]}×{settings["height"]}, в эталоне {width}×{height}; требуется создание/перестройка нативной Sequence.')
            except (TypeError, ValueError):
                raise
        period = self._frame_rate_period(settings.get('frame_rate'))
        native_period = video.findtext('./TrackGroup/FrameRate')
        if period and native_period and abs(period - int(native_period)) > 1:
            raise ValueError(f'«{name}»: частота кадров отличается от эталонной; перестройка нативной Sequence пока не реализована.')

    def _source_for_fc_clip(self, clip: dict, kind: str) -> ET.Element | None:
        if self._fc_item_kind(clip) == 'sequence':
            # Nested sequence source chains are kept from the graph template when
            # the aligned clip already refers to the same sequence.
            return None
        path = self._fc_media_path(self._media_item(clip.get('item')))
        if not path:
            return None
        index = 0
        if kind == 'audio':
            try:
                index = max(0, int(clip.get('audio_stream', 0) or 0))
            except (ValueError, TypeError):
                index = 0
        entry = self.native_media_sources.get((path, kind, index))
        return entry[0] if entry else None

    def _update_clip_instance(self, native_item: ET.Element, fc_clip: dict, kind: str, sequence_name: str) -> None:
        clip_item = native_item.find('./ClipTrackItem')
        if clip_item is None:
            raise ValueError(f'«{sequence_name}»: неожиданная структура TrackItem {native_item.get("ObjectID")}.')
        subclip_ref = clip_item.find('SubClip')
        subclip = self.resolve(subclip_ref)
        if subclip is None:
            raise ValueError(f'«{sequence_name}»: не разрешается SubClip для TrackItem {native_item.get("ObjectID")}.')
        native_clip = self.resolve(subclip.find('Clip'))
        if native_clip is None:
            raise ValueError(f'«{sequence_name}»: не разрешается Clip для SubClip {subclip.get("ObjectID")}.')
        clip_node = native_clip.find('Clip')
        if clip_node is None:
            raise ValueError(f'«{sequence_name}»: отсутствует внутренний Clip-узел.')

        # Rewrite source link only when the FC asset is a normal media item. Nested
        # sequence sources are preserved from the matching native-template event.
        replacement_source = self._source_for_fc_clip(fc_clip, kind)
        if self._fc_item_kind(fc_clip) == 'media':
            if replacement_source is None:
                media_path = self._fc_media_path(self._media_item(fc_clip.get('item')))
                raise ValueError(f'«{sequence_name}»: медиа «{fc_clip.get("name", media_path)}» отсутствует в графе Premiere-эталона; пока не поддерживается создание новых media/master-clip объектов.')
            source_ref = clip_node.find('Source')
            if source_ref is None:
                source_ref = ET.SubElement(clip_node, 'Source')
            source_id = replacement_source.get('ObjectID')
            source_uid = replacement_source.get('ObjectUID')
            source_ref.attrib.clear()
            if source_id:
                source_ref.set('ObjectRef', source_id)
            elif source_uid:
                source_ref.set('ObjectURef', source_uid)
            # The SubClip points at the source's master clip, so update that link
            # from an existing subclip that uses this same source/master pair.
            master_uid = self._master_uid_for_source(replacement_source)
            if master_uid:
                master_ref = subclip.find('MasterClip')
                if master_ref is not None:
                    master_ref.attrib.clear(); master_ref.set('ObjectURef', master_uid)
            if kind == 'audio':
                stream_index = max(0, int(fc_clip.get('audio_stream', 0) or 0))
                self._set_child_text(native_clip, 'SecondaryIndex', str(stream_index))
            name = str(fc_clip.get('name') or '')
            name_node = subclip.find('Name')
            if name_node is None:
                name_node = ET.SubElement(subclip, 'Name')
            if name:
                name_node.text = name

        try:
            start = int(fc_clip.get('start', 0) or 0)
            duration = int(fc_clip.get('duration', 0) or 0)
            source_in = int(fc_clip.get('source_in', 0) or 0)
            speed = float(fc_clip.get('speed', 1.0) or 1.0)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'«{sequence_name}»: некорректные тайминги клипа {fc_clip.get("name", "")}.') from exc
        if duration < 0 or speed <= 0:
            raise ValueError(f'«{sequence_name}»: отрицательная длительность или обратная скорость клипа «{fc_clip.get("name", "") }» пока не поддерживается.')
        track_node = clip_item.find('TrackItem')
        if track_node is None:
            raise ValueError(f'«{sequence_name}»: отсутствует TrackItem timing node.')
        self._set_child_text(track_node, 'Start', str(start))
        self._set_child_text(track_node, 'End', str(start + duration))
        self._set_child_text(clip_node, 'InPoint', str(source_in))
        self._set_child_text(clip_node, 'OutPoint', str(source_in + round(duration * speed)))
        if abs(speed - 1.0) > 1e-9:
            self.warnings.append(f'«{sequence_name}» / «{fc_clip.get("name", "клип") }»: скорость {speed:g} не записана в native time-remap, обновлены только source out-point и длительность.')

    @staticmethod
    def _set_child_text(parent: ET.Element, tag: str, value: str) -> None:
        node = parent.find(tag)
        if node is None:
            node = ET.SubElement(parent, tag)
        node.text = value

    def _master_uid_for_source(self, source: ET.Element) -> str | None:
        source_id = source.get('ObjectID')
        source_uid = source.get('ObjectUID')
        for subclip in self.root.iter('SubClip'):
            clip = self.resolve(subclip.find('Clip'))
            inner = clip.find('Clip') if clip is not None else None
            source_ref = inner.find('Source') if inner is not None else None
            resolved = self.resolve(source_ref)
            if resolved is not None and (resolved is source or (source_id and resolved.get('ObjectID') == source_id) or (source_uid and resolved.get('ObjectUID') == source_uid)):
                master = subclip.find('MasterClip')
                if master is not None:
                    if master.get('ObjectURef'):
                        return master.get('ObjectURef')
                    master_obj = self.resolve(master)
                    return master_obj.get('ObjectUID') if master_obj is not None else None
        return None

    def write(self, output: Path) -> list[str]:
        if not self.sequence_by_name:
            raise ValueError('В Premiere-эталоне не найдены Sequence-объекты. Нужен populated project graph, не пустая оболочка.')
        fc_sequences = [x for x in self.items.values() if 'Sequence' in x.get('kind', {})]
        if not fc_sequences:
            raise ValueError('В FilmCraft проекте не найдено ни одной последовательности.')
        if len(fc_sequences) != len(self.sequence_by_name):
            self.warnings.append(f'В эталоне {len(self.sequence_by_name)} последовательностей, в FilmCraft {len(fc_sequences)}; эталонные лишние последовательности сохраняются.')

        aligned = 0
        for sequence_item in fc_sequences:
            name = str(sequence_item.get('name') or '')
            native_seq = self.sequence_by_name.get(name)
            if native_seq is None:
                raise ValueError(f'Последовательность «{name}» отсутствует в Premiere-эталоне; создание новых Sequence-объектов пока не реализовано.')
            fc_seq = self._fc_sequence_item(sequence_item)
            groups = self._sequence_track_groups(native_seq)
            self._validate_settings(name, fc_seq, groups)
            for kind in ('video', 'audio'):
                fc_tracks = fc_seq.get(f'{kind}_tracks', []) or []
                native_group = groups.get(kind)
                native_tracks = self._native_tracks(native_group) if native_group is not None else []
                if len(fc_tracks) != len(native_tracks):
                    raise ValueError(f'«{name}»: число {kind}-дорожек не совпадает с эталоном ({len(fc_tracks)} vs {len(native_tracks)}); создание дорожек пока не реализовано.')
                for track_ix, (fc_track, native_track) in enumerate(zip(fc_tracks, native_tracks), 1):
                    fc_clips = sorted(fc_track.get('items', []) or [], key=lambda c: (int(c.get('start', 0) or 0), int(c.get('id', 0) or 0)))
                    native_items = self._native_track_items(native_track)
                    if len(fc_clips) != len(native_items):
                        raise ValueError(f'«{name}»: {kind} {track_ix}: число клипов не совпадает с эталоном ({len(fc_clips)} vs {len(native_items)}); добавление/удаление clip graph пока не реализовано.')
                    for fc_clip, native_item in zip(fc_clips, native_items):
                        self._update_clip_instance(native_item, fc_clip, kind, name)
                        aligned += 1

        # Keep the project graph native, but use the supplied empty shell's build
        # metadata and a fresh project GUID after graph alignment has succeeded.
        self._apply_blank_shell_metadata()
        output.parent.mkdir(parents=True, exist_ok=True)
        self.tree.write(output, encoding='utf-8', xml_declaration=True)
        self.warnings.insert(0, f'Обновлено существующих clip instances: {aligned}. Граф Sequence/Track взят из Premiere-эталона.')
        self.warnings.append('Ограничение первого writer: сохраняются только уже существующие в эталоне sequences/tracks/clips; новые медиа, sequence, дорожки, переходы и эффекты пока не создаются.')
        return self.warnings


def main() -> int:
    parser = argparse.ArgumentParser(description='Best-effort FilmCraft JSON → native Premiere .prproj writer')
    parser.add_argument('input', type=Path, help='FilmCraft .fcproj JSON project')
    parser.add_argument('output', type=Path, nargs='?', help='Native Premiere .prproj output')
    parser.add_argument('--reference', type=Path, required=True, help='Populated Premiere .prproj used as the native graph template')
    parser.add_argument('--shell', type=Path, required=True, help='Empty Premiere .prproj shell for build/project metadata')
    args = parser.parse_args()
    output = args.output or args.input.with_suffix('.prproj')
    writer = NativeWriter(args.input, args.reference, args.shell)
    warnings = writer.write(output)
    report = output.with_name(output.stem + '_conversion_report.md')
    report.write_text('# Отчёт FilmCraft → native Premiere\n\n'
                      f'- FilmCraft: `{args.input.name}`\n- Premiere graph reference: `{args.reference.name}`\n- Premiere shell: `{args.shell.name}`\n- Результат: `{output.name}`\n\n'
                      '## Результат и ограничения\n\n' + '\n'.join('- ' + x for x in warnings) + '\n', encoding='utf-8')
    print(f'Created {output}\nCreated {report}\n' + warnings[0])
    if len(warnings) > 2:
        print(f'Warnings: {len(warnings)-2}')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'Conversion failed: {exc}', file=sys.stderr)
        raise
