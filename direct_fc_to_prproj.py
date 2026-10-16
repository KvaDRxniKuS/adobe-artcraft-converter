"""Experimental FilmCraft -> native Premiere graph writer.

Builds media, sequence, track, and clip objects from FilmCraft references, using
an embedded neutral Premiere graph seed for object layouts. A user-supplied
Premiere project containing the same media/timeline is NOT needed. Native
Premiere compatibility still requires validation in Premiere Pro.
"""
from __future__ import annotations

import base64
import copy
import gzip
import json
import os
import re
import tempfile
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from fcproj_to_prproj import TICKS, same_file
from graphic_raster import render_graphic
from premiere_seed import load_seed_xml
from premiere_text import NativeTextUnsupported, create_native_text
from premiere_text_seed import load_text_seed_xml
from prproj_to_fcproj import Converter as ForwardConverter

# These records describe the project shell; all media/timeline records are
# generated afresh and linked from its root bin.
SHELL_RECORDS = frozenset({
    'Project', 'RootProjectItem', 'ProjectSettings', 'CompileSettings',
    'ScratchDiskSettings', 'IngestSettings', 'WorkspaceSettings',
    'DummyCaptureSettings', 'DefaultSequenceSettings', 'VideoSettings',
    'AudioSettings', 'VideoCompileSettings', 'AudioCompileSettings',
})
GUID = re.compile(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z')
# ImplementationID is a shared importer type ID, not an object identity:
# file-backed media and synthetic titles each use a specific constant GUID.
IDENTITY_TAGS = frozenset({'ID', 'ClipID', 'FileKey',
                           'DefMappingID', 'PreviewFormatIdentifier'})
AUDIO_EXTENSIONS = {'.wav', '.mp3', '.aif', '.aiff', '.m4a', '.flac', '.aac', '.ogg'}
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp', '.gif', '.webp'}
STILL_DURATION = 10973491200000000


@dataclass(frozen=True)
class MediaHandle:
    master_uid: str
    video_source: str | None
    audio_source: str | None
    name: str
    width: int
    height: int
    channels: int


@dataclass
class SequencePlan:
    item_id: str
    name: str
    sequence: dict
    cloned: dict[ET.Element, ET.Element]
    native_seq: ET.Element
    width: int
    height: int
    frame_rate: int
    sample_rate: int


class GraphIndex:
    """Top-level Premiere objects are addressed by ObjectID or ObjectUID."""

    def __init__(self, root: ET.Element):
        self.root = root
        self.by_id = {el.get('ObjectID'): el for el in root if el.get('ObjectID')}
        self.by_uid = {el.get('ObjectUID'): el for el in root if el.get('ObjectUID')}

    def resolve(self, element: ET.Element | None) -> ET.Element | None:
        if element is None:
            return None
        if element.get('ObjectRef'):
            return self.by_id.get(element.get('ObjectRef'))
        if element.get('ObjectURef'):
            return self.by_uid.get(element.get('ObjectURef'))
        return element

    def from_path(self, element: ET.Element, path: str) -> ET.Element:
        found = self.resolve(element.find(path))
        if found is None:
            raise ValueError(f'Premiere seed lacks {path}')
        return found


class GraphBuilder:
    """Clone seed object layouts and allocate fresh references for each object."""

    def __init__(self):
        seed = ET.fromstring(load_seed_xml())
        if seed.tag != 'PremiereData':
            raise ValueError('Invalid embedded Premiere seed')
        self.template = GraphIndex(seed)
        self.media_bin = next(el for el in seed if el.tag == 'ClipProjectItem'
                              and el.findtext('./ProjectItem/Name') == 'seed-placeholder.mp4')
        self.sequence_bin = next(el for el in seed if el.tag == 'ClipProjectItem'
                                 and el.findtext('./ProjectItem/Name') == 'Seed Sequence')
        self.media_master = self.template.from_path(self.media_bin, 'MasterClip')
        media_clips = [self.template.resolve(ref)
                       for ref in self.media_master.findall('./Clips/Clip')]
        self.source = {}
        for kind, tag in (('video', 'VideoClip'), ('audio', 'AudioClip')):
            clip = next(item for item in media_clips if item is not None and item.tag == tag)
            self.source[kind] = self.template.from_path(clip, './Clip/Source')

        seq = self.template.from_path(
            self.template.from_path(self.sequence_bin, 'MasterClip'),
            './Clips/Clip')
        seq_source = self.template.from_path(seq, './Clip/Source')
        self.sequence_template = self.template.from_path(seq_source, './SequenceSource/Sequence')
        self.group_templates = {}
        self.track_templates = {}
        self.occurrence_templates = {}
        for group_ref in self.sequence_template.findall('./TrackGroups/TrackGroup/Second'):
            group = self.template.resolve(group_ref)
            if group is None or group.tag not in ('VideoTrackGroup', 'AudioTrackGroup'):
                continue
            kind = 'video' if group.tag == 'VideoTrackGroup' else 'audio'
            self.group_templates[kind] = group
            track = self.template.from_path(group, './TrackGroup/Tracks/Track')
            self.track_templates[kind] = track
            self.occurrence_templates[kind] = self.template.from_path(
                track, './ClipTrack/ClipItems/TrackItems/TrackItem')

        # The copy used for sequence/track cloning has NO example timeline items
        # or links. This prevents a template media reference from leaking into output.
        clean = copy.deepcopy(seed)
        for track in clean:
            if track.tag in ('VideoClipTrack', 'AudioClipTrack'):
                items = track.find('./ClipTrack/ClipItems/TrackItems')
                if items is not None:
                    items.clear()
        for seq_node in clean.findall('Sequence'):
            links = seq_node.find('./PersistentGroupContainer/LinkContainer/Links')
            if links is not None:
                links.clear()
        self.clean = GraphIndex(clean)
        self.output = ET.Element('PremiereData', seed.attrib.copy())
        for element in seed:
            if element.tag in SHELL_RECORDS or element.get('ObjectRef') == '1':
                self.output.append(copy.deepcopy(element))
        self.shell_objects = set(self.output)
        self.root_bin = next(el for el in self.output if el.tag == 'RootProjectItem')
        self.bin_items = self.root_bin.find('./ProjectItemContainer/Items')
        if self.bin_items is None:
            raise ValueError('Premiere seed has no root bin items')
        self.bin_items.clear()
        ids = [int(el.get('ObjectID')) for el in seed.iter()
               if (el.get('ObjectID') or '').isdecimal()]
        self.next_id = max(ids, default=0) + 1

    def alloc(self) -> str:
        value = str(self.next_id)
        self.next_id += 1
        return value

    def clone(self, graph: GraphIndex, start: ET.Element,
              overrides: dict[tuple[str, str], str] | None = None) -> dict[ET.Element, ET.Element]:
        """Clone every referenced top-level object, remapping internal IDs/UIDs."""
        overrides = overrides or {}
        found: set[ET.Element] = set()
        pending = [start]
        while pending:
            current = pending.pop()
            if current in found:
                continue
            found.add(current)
            for child in current.iter():
                for attr, lookup in (('ObjectRef', graph.by_id), ('ObjectURef', graph.by_uid)):
                    ref = child.get(attr)
                    if ref and (attr, ref) not in overrides:
                        target = lookup.get(ref)
                        if target is not None and target not in found:
                            pending.append(target)
        selected = [item for item in graph.root if item in found]
        id_map = {item.get('ObjectID'): self.alloc()
                  for item in selected if item.get('ObjectID')}
        uid_map = {item.get('ObjectUID'): str(uuid.uuid4())
                   for item in selected if item.get('ObjectUID')}
        copied: dict[ET.Element, ET.Element] = {}
        for item in selected:
            node = copy.deepcopy(item)
            for child in node.iter():
                if child.get('ObjectID') in id_map:
                    child.set('ObjectID', id_map[child.get('ObjectID')])
                if child.get('ObjectUID') in uid_map:
                    child.set('ObjectUID', uid_map[child.get('ObjectUID')])
                for attr, mapping in (('ObjectRef', id_map), ('ObjectURef', uid_map)):
                    value = child.get(attr)
                    if value:
                        child.set(attr, overrides.get((attr, value), mapping.get(value, value)))
                if (child.tag in IDENTITY_TAGS and child.text
                        and GUID.fullmatch(child.text.strip())):
                    child.text = str(uuid.uuid4())
            self.output.append(node)
            copied[item] = node
        return copied

    def append_bin(self, project_item: ET.Element) -> None:
        ET.SubElement(self.bin_items, 'Item', {
            'Index': str(len(self.bin_items)), 'ObjectURef': project_item.get('ObjectUID'),
        })

    def remove_orphans(self) -> None:
        """Drop unused example tracks/objects after replacing template links."""
        index = GraphIndex(self.output)
        reachable: set[ET.Element] = set(self.shell_objects)
        pending = list(self.shell_objects)
        while pending:
            node = pending.pop()
            for child in node.iter():
                for attr, lookup in (('ObjectRef', index.by_id), ('ObjectURef', index.by_uid)):
                    target = lookup.get(child.get(attr)) if child.get(attr) else None
                    if target is not None and target not in reachable:
                        reachable.add(target)
                        pending.append(target)
        for node in list(self.output):
            if node not in reachable:
                self.output.remove(node)
        index = GraphIndex(self.output)
        if len(index.by_id) != len([el for el in self.output if el.get('ObjectID')]):
            raise ValueError('Duplicate Premiere ObjectID')
        if len(index.by_uid) != len([el for el in self.output if el.get('ObjectUID')]):
            raise ValueError('Duplicate Premiere ObjectUID')
        for node in self.output:
            if node in self.shell_objects:
                continue  # the seed's project-view settings use nested/local IDs
            for el in node.iter():
                if (el.get('ObjectRef') and el.get('ObjectRef') not in index.by_id
                        or el.get('ObjectURef') and el.get('ObjectURef') not in index.by_uid):
                    raise ValueError(f'Unresolved native reference in {node.tag}')


class DirectWriter:
    """Build native object links directly from the FC project, without PR inputs."""

    def __init__(self, fc_path: Path, shell_path: Path | None = None,
                 graphic_mode: str = 'native'):
        if graphic_mode not in ('native', 'png'):
            raise ValueError('Режим Graphic должен быть native или png.')
        self.graphic_mode = graphic_mode
        self.fc_path = Path(fc_path)
        self.shell_path = Path(shell_path) if shell_path else None
        self.fc = json.loads(self.fc_path.read_text(encoding='utf-8-sig'))
        if not isinstance(self.fc, dict) or self.fc.get('format') != 'filmcraft.project':
            raise ValueError('Входной JSON не является проектом FilmCraft (format=filmcraft.project).')
        project = self.fc.get('project') or {}
        raw_items = project.get('items') or {}
        if not isinstance(raw_items, dict) or any(not isinstance(item, dict)
                                                  for item in raw_items.values()):
            raise ValueError('FilmCraft project.items должен быть словарём элементов.')
        self.items = {str(k): v for k, v in raw_items.items()}
        # Some exports keep a clip's numeric item ID in item['id'] while using a
        # different key in project.items. Resolve that ID only when unambiguous.
        self.declared_ids: dict[str, list[str]] = {}
        for key, item in self.items.items():
            if item.get('id') is not None:
                self.declared_ids.setdefault(str(item['id']), []).append(key)
        self.project = project
        self.warnings: list[str] = []
        self.resolved_aliases: set[str] = set()
        self.graph = GraphBuilder()
        self.media: dict[str, MediaHandle] = {}
        self.sequence_handles: dict[str, MediaHandle] = {}
        self.plans: list[SequencePlan] = []
        self.media_needed_span: dict[str, int] = {}
        self.generated_assets: dict[Path, bytes] = {}
        self.output_path: Path | None = None
        self.text_template: GraphIndex | None = None

    @staticmethod
    def _set(node: ET.Element, path: str, value: object) -> None:
        target = node
        for tag in path.removeprefix('./').split('/'):
            child = target.find(tag)
            if child is None:
                child = ET.Element(tag)
                # Match the native record order when adding timing fields that
                # the zero-start graph seed legitimately omits.
                before = ('End' if target.tag == 'TrackItem' and tag == 'Start' else
                          'InPoint' if target.tag == 'Clip' and tag == 'OutPoint' else
                          'ClipID' if target.tag == 'Clip' and tag in ('InPoint', 'OutPoint')
                          else None)
                anchor = target.find(before) if before else None
                if anchor is not None:
                    target.insert(list(target).index(anchor), child)
                else:
                    target.append(child)
            target = child
        target.text = str(value)

    @staticmethod
    def _period(rate: dict | None, default: int) -> int:
        try:
            numerator = int(rate['num'])
            denominator = int(rate['den'])
            if numerator > 0 and denominator > 0:
                return max(1, round(TICKS * denominator / numerator))
        except (KeyError, ValueError, TypeError, ZeroDivisionError):
            pass
        return default

    def _media_path(self, item: dict) -> str:
        value = item.get('kind', {}).get('Media', {}).get('media', {})
        path = (value.get('File') or {}).get('path') or value.get('path') or value.get('url') or ''
        if not isinstance(path, str):
            raise ValueError('FilmCraft media path must be a string')
        return path.strip()

    def _item_key(self, ref: object) -> str:
        """Resolve a timeline item by storage key, then by a unique declared ID."""
        value = str(ref)
        if value in self.items:
            return value
        keys = self.declared_ids.get(value, [])
        if len(keys) > 1:
            raise ValueError(f'FilmCraft ID {value} неоднозначен: элементы project.items '
                             f'{", ".join(keys)} имеют одинаковое поле id.')
        if keys:
            if value not in self.resolved_aliases:
                self.warnings.append(f'Ссылка на ID {value} найдена по полю id элемента '
                                     f'project.items[{keys[0]!r}], а не по его ключу.')
                self.resolved_aliases.add(value)
            return keys[0]
        return value

    @staticmethod
    def _adapt_audio_layout(objects, channels: int) -> None:
        layout = json.dumps([{'channellabel': 100 + i} for i in range(channels)],
                            separators=(',', ':'))
        for node in objects:
            if node.tag in ('AudioStream', 'AudioClip', 'AudioComponentChain'):
                setting = node.find('AudioChannelLayout')
                if setting is not None:
                    setting.text = layout
            if node.tag == 'AudioClip':
                content = node.find('SecondaryContents')
                if content is not None:
                    for ref in list(content)[channels:]:
                        content.remove(ref)
            if node.tag == 'ClipChannelVectorSerializer':
                refs = node.find('ClipChannels')
                if refs is not None:
                    for ref in list(refs)[channels:]:
                        refs.remove(ref)

    def _make_media(self, item_id: str, item: dict, *, generated: bool = False) -> None:
        path = self._media_path(item)
        name = str(item.get('name') or Path(path.replace('\\', '/')).name or 'Media')
        if not path:
            raise ValueError(f'Медиа «{name}» без пути: создание офлайн-источника Premiere пока не поддерживается.')
        candidate = Path(path)
        if not generated and not candidate.is_absolute() and (self.fc_path.parent / candidate).is_file():
            path = str((self.fc_path.parent / candidate).resolve())
        raw_info = item.get('kind', {}).get('Media', {}).get('info') or {}
        info = raw_info if isinstance(raw_info, dict) else {}
        video = info.get('video') if isinstance(info.get('video'), dict) else None
        audio_streams = info.get('audio_streams') if isinstance(info.get('audio_streams'), list) else []
        suffix = Path(path.replace('\\', '/')).suffix.lower()
        media_kind = str(info.get('kind') or '').casefold()
        is_still = generated or media_kind == 'still' or (
            not media_kind and suffix in IMAGE_EXTENSIONS)
        if not video and not audio_streams:
            if Path(path).suffix.lower() in AUDIO_EXTENSIONS:
                audio_streams = [{'sample_rate': 48000, 'channels': 2}]
            else:
                video = {'width': 1920, 'height': 1080, 'frame_rate': {'num': 24, 'den': 1}}
            self.warnings.append(f'«{name}»: в FC нет параметров медиа; использованы предварительные значения.')
        width = max(1, int((video or {}).get('width') or 1920))
        height = max(1, int((video or {}).get('height') or 1080))
        first_audio = (audio_streams[0] or {}) if audio_streams else {}
        channels = max(1, min(2, int(first_audio.get('channels') or 2)))
        if len(audio_streams) > 1 or int(first_audio.get('channels') or 2) > 2:
            self.warnings.append(f'«{name}»: в Premiere сохранена базовая стереопара; '
                                 'дополнительные аудиоканалы/потоки проверьте вручную.')
        duration = max(1, int(info.get('duration') or TICKS * 5),
                       self.media_needed_span.get(item_id, 0))
        project_item = self.graph.clone(self.graph.template, self.graph.media_bin)
        media = next(value for value in project_item.values() if value.tag == 'Media')
        master = project_item[self.graph.media_master]
        bin_item = project_item[self.graph.media_bin]
        self._set(bin_item, './ProjectItem/Name', name)
        self._set(master, 'Name', name)
        for value in project_item.values():
            if value.tag == 'ClipLoggingInfo':
                clip_name = value.find('ClipName')
                if clip_name is not None:
                    clip_name.text = name
            if value.tag.endswith('MediaSource'):
                self._set(value, 'OriginalDuration', duration)
            if value.tag in ('AudioStream', 'VideoStream'):
                self._set(value, 'Duration', duration)
        # Preserve the seed Media record's version-specific path fields; adding
        # unrelated tags could make Premiere reject an otherwise valid record.
        paths = [media.find(tag) for tag in
                 ('ActualMediaFilePath', 'FilePath', 'RelativePath')]
        for field in paths:
            if field is not None:
                field.text = path
        if not any(field is not None for field in paths):
            self._set(media, 'RelativePath', path)
        self._set(media, 'Title', name)
        # Keep the file importer GUID from the Premiere fixture; FileKey is unique.
        self._set(media, 'FileKey', str(uuid.uuid4()))
        if video:
            vs = next(value for value in project_item.values() if value.tag == 'VideoStream')
            self._set(vs, 'FrameRect', f'0,0,{width},{height}')
            self._set(vs, 'FrameRate', self._period(video.get('frame_rate'), 10594584000))
            if is_still:
                # Match the native still-image layout rather than carrying MP4
                # codec/alpha metadata into a PNG (including FC's own stills).
                self._set(media, 'Infinite', 'true')
                self._set(vs, 'IsStill', 'true')
                self._set(vs, 'Duration', STILL_DURATION)
                self._set(vs, 'CodecType', 1380013856)
                self._set(vs, 'PARIsUncertain', 'true')
                self._set(vs, 'FieldTypeIsUncertain', 'true')
                if generated or video.get('has_alpha'):
                    self._set(vs, 'AlphaType', 1)
                else:
                    alpha = vs.find('AlphaType')
                    if alpha is not None:
                        vs.remove(alpha)
                for tag in ('IgnoreAlpha', 'OriginalColorSpace',
                            'OriginalImageOrientationType'):
                    old = vs.find(tag)
                    if old is not None:
                        vs.remove(old)
                for value in project_item.values():
                    if value.tag == 'VideoMediaSource':
                        self._set(value, 'OriginalDuration', STILL_DURATION)
        else:
            stream = media.find('VideoStream')
            if stream is not None:
                media.remove(stream)
        if audio_streams:
            audio = next(value for value in project_item.values() if value.tag == 'AudioStream')
            rate = max(1, int(first_audio.get('sample_rate') or 48000))
            self._set(audio, 'FrameRate', max(1, round(TICKS / rate)))
            layout = [{'channellabel': 100 + channel} for channel in range(channels)]
            self._set(audio, 'AudioChannelLayout', json.dumps(layout, separators=(',', ':')))
        else:
            stream = media.find('AudioStream')
            if stream is not None:
                media.remove(stream)
        if audio_streams:
            self._adapt_audio_layout(project_item.values(), channels)
        for ref in list(master.findall('./Clips/Clip')):
            native = next((v for v in project_item.values()
                           if v.get('ObjectID') == ref.get('ObjectRef')), None)
            if native is not None and ((native.tag == 'VideoClip' and not video)
                                       or (native.tag == 'AudioClip' and not audio_streams)):
                master.find('Clips').remove(ref)
        self.graph.append_bin(bin_item)
        self.media[item_id] = MediaHandle(master.get('ObjectUID'),
                                          project_item[self.graph.source['video']].get('ObjectID') if video else None,
                                          project_item[self.graph.source['audio']].get('ObjectID') if audio_streams else None,
                                          name, width, height, channels)
        if not generated and not Path(path).is_file():
            self.warnings.append(f'«{name}»: проверьте путь к исходному файлу в Premiere.')

    def _make_graphic_media(self, item_id: str, item: dict, clip: dict,
                            width: int, height: int) -> MediaHandle:
        if self.output_path is None:
            raise RuntimeError('Output path is not configured')
        graphic = item['kind']['Graphic']
        if not isinstance(graphic, dict):
            raise ValueError(f'Graphic {item_id} не содержит параметров холста.')
        png, messages, text_drawn = render_graphic(
            graphic, clip.get('effects') or [], width, height)
        filename = (f'{self.output_path.stem}_graphic_'
                    f'{len(self.generated_assets) + 1}_{uuid.uuid4().hex}.png')
        path = self.output_path.parent / filename
        self.generated_assets[path] = png
        name = str(clip.get('name') or item.get('name') or 'Graphic')
        pseudo_id = f'Graphic:{item_id}:{uuid.uuid4().hex}'
        pseudo_item = {'name': name, 'kind': {'Media': {
            # The Premiere seed uses RelativePath. Keep generated assets portable
            # with the .prproj when both files are moved together.
            'media': {'File': {'path': filename}},
            'info': {'kind': 'Still', 'duration': max(1,
                int(clip.get('source_in') or 0) + int(clip.get('duration') or 0)),
                     'video': {'width': graphic.get('width') or width,
                               'height': graphic.get('height') or height,
                               'frame_rate': graphic.get('rate')},
                     'audio_streams': []},
        }}}
        self._make_media(pseudo_id, pseudo_item, generated=True)
        self.warnings.append(f'«{name}»: Graphic {item_id} сохранён как растровый PNG '
                             'рядом с проектом; текст не редактируется как титр Premiere.')
        if not text_drawn:
            self.warnings.append(f'«{name}»: содержимое Graphic не удалось отобразить; '
                                 'создан прозрачный PNG, проверьте этот клип.')
        self.warnings.extend(f'«{name}»: {message}' for message in messages)
        return self.media[pseudo_id]

    def _make_native_text_clip(self, item: dict, clip: dict, effect: dict,
                               width: int, height: int, frame_period: int,
                               start: int, duration: int, source_in: int) -> ET.Element:
        """Clone a Type-tool title graph and write an editable Source Text blob."""
        native = create_native_text(effect, item['kind']['Graphic'], width, height)
        if self.text_template is None:
            self.text_template = GraphIndex(ET.fromstring(load_text_seed_xml()))
        template = self.text_template
        occurrence = next(el for el in template.root if el.tag == 'VideoClipTrackItem')
        copied = self.graph.clone(template, occurrence)
        track_item = copied[occurrence]
        sub_template = template.from_path(occurrence, './ClipTrackItem/SubClip')
        sub = copied[sub_template]
        placed = copied[template.from_path(sub_template, 'Clip')]
        master_template = template.from_path(sub_template, 'MasterClip')
        master = copied[master_template]
        source_clip = copied[template.from_path(master_template, './Clips/Clip')]
        name = str(clip.get('name') or item.get('name') or 'Graphic text')
        self._set(sub, 'Name', name)
        self._set(master, 'Name', name)
        self._set(track_item, './ClipTrackItem/TrackItem/Start', start)
        self._set(track_item, './ClipTrackItem/TrackItem/End', start + duration)
        self._set(track_item, 'FrameRect', f'0,0,{width},{height}')
        self._set(placed, './Clip/InPoint', source_in)
        self._set(placed, './Clip/OutPoint', source_in + duration)
        self._set(source_clip, './Clip/OutPoint', source_in + duration)
        for node in copied.values():
            if node.tag == 'VideoStream':
                self._set(node, 'FrameRate', frame_period)
                self._set(node, 'FrameRect', f'0,0,{width},{height}')
            elif node.tag == 'ClipLoggingInfo':
                self._set(node, 'ClipName', name)
                self._set(node, 'MediaFrameRate', frame_period)
            elif node.tag == 'Media':
                # This is Premiere's *synthetic graphic importer* identifier,
                # not a per-file identity. GraphBuilder randomizes GUID fields.
                self._set(node, 'ImplementationID', '42008e7a-de6f-4270-96de-7e287abb9b4b')
            elif node.tag == 'ArbVideoComponentParam':
                blob = node.find('StartKeyframeValue')
                if blob is None:
                    raise ValueError('Premiere text seed lacks Source Text payload')
                blob.text = base64.b64encode(native.payload).decode('ascii')
                blob.set('BinaryHash', str(uuid.uuid4()))
            elif node.tag in ('PointComponentParam', 'VideoComponentParam'):
                try:
                    param_id = int(node.findtext('ParameterID') or '')
                except ValueError:
                    continue
                if param_id in native.parameters:
                    start_key = node.find('StartKeyframe')
                    if start_key is None or not start_key.text:
                        raise ValueError(f'Premiere text seed lacks parameter {param_id}')
                    fields = start_key.text.split(',')
                    fields[1] = native.parameters[param_id]
                    start_key.text = ','.join(fields)
            elif node.tag == 'VideoFilterComponent':
                self._set(node, './Component/InstanceName', name)
        self.warnings.extend(f'«{name}»: {message}' for message in native.warnings)
        return track_item

    def _make_clip(self, kind: str, clip: dict, sequence_name: str,
                   width: int, height: int, frame_period: int) -> ET.Element:
        raw_id = str(clip.get('item'))
        media_id = self._item_key(clip.get('item'))
        source = self.items.get(media_id)
        is_graphic = source is not None and 'Graphic' in source.get('kind', {})
        handle = self.media.get(media_id)
        if is_graphic and kind != 'video':
            raise ValueError(f'«{sequence_name}»: Graphic {raw_id} нельзя поместить на аудиодорожку.')
        if handle is None and not is_graphic:
            clip_name = clip.get('name') or 'Без имени'
            if source is None:
                raise ValueError(f'«{sequence_name}»: клип «{clip_name}» ссылается на '
                                 f'отсутствующее медиа {raw_id}: элемента с таким ключом '
                                 'или полем id нет в project.items.')
            if 'Media' in source.get('kind', {}) and not self._media_path(source):
                raise ValueError(f'«{sequence_name}»: клип «{clip_name}» ссылается на '
                                 f'медиа {raw_id} «{source.get("name", "") }» без пути; '
                                 'вложенная последовательность с таким именем не найдена.')
            kinds = ', '.join(source.get('kind', {})) or 'не указан'
            raise ValueError(f'«{sequence_name}»: клип «{clip_name}» ссылается на '
                             f'элемент {raw_id} «{source.get("name", "") }» с kind={kinds}; '
                             'FC → PR пока не поддерживает этот тип источника.')
        clip_name = str(clip.get('name') or (handle.name if handle else source.get('name')))
        start = int(clip.get('start') or 0)
        duration = int(clip.get('duration') or 0)
        source_in = int(clip.get('source_in') or 0)
        speed = 1.0 if clip.get('speed') is None else float(clip['speed'])
        if min(start, source_in) < 0 or duration <= 0 or not (0 < speed < 1000) or clip.get('reverse'):
            raise ValueError(f'«{sequence_name}»: отрицательные тайминги, нулевая длительность '
                             'или обратное воспроизведение не поддерживаются.')
        if speed != 1:
            self.warnings.append(f'«{sequence_name}» / «{clip_name}»: '
                                 f'изменение скорости {speed:g} не перенесено, проверьте тайминг.')
        if clip.get('enabled') is False:
            self.warnings.append(f'«{sequence_name}» / «{clip_name}»: '
                                 'отключённый клип записан активным.')
        if (clip.get('markers') or clip.get('frame_hold') or clip.get('multicam')
                or clip.get('essential') or clip.get('scale_to_frame')):
            self.warnings.append(f'«{sequence_name}» / «{clip_name}»: '
                                 'специальные параметры или маркеры клипа не перенесены.')
        defaults = {effect['effect']: effect.get('params')
                    for effect in (ForwardConverter.intrinsic_video(width, height)
                                   if kind == 'video' else ForwardConverter.intrinsic_audio())}
        effects = [effect for effect in (clip.get('effects') or [])
                   if not (is_graphic and isinstance(effect, dict)
                           and effect.get('effect') == 'graphic_text')
                   and (not isinstance(effect, dict)
                        or effect.get('effect') not in defaults
                        or effect.get('params') != defaults[effect['effect']]
                        or effect.get('enabled') is False)]
        if effects:
            self.warnings.append(f'«{sequence_name}» / «{clip_name}»: '
                                 f'{len(effects)} эффект(ов) или изменённых параметров '
                                 'не перенесено.')
        if is_graphic:
            if self.graphic_mode == 'native':
                layers = [effect for effect in (clip.get('effects') or [])
                          if isinstance(effect, dict) and effect.get('effect') == 'graphic_text']
                if len(layers) == 1:
                    try:
                        return self._make_native_text_clip(source, clip, layers[0],
                                                           width, height, frame_period,
                                                           start, duration, source_in)
                    except NativeTextUnsupported as exc:
                        self.warnings.append(f'«{clip_name}»: нативный текст недоступен ({exc}); '
                                             'использован PNG.')
                elif len(layers) > 1:
                    self.warnings.append(f'«{clip_name}»: несколько слоёв текста пока '
                                         'сохраняются как PNG.')
            else:
                self.warnings.append(f'«{clip_name}»: выбран режим совместимости PNG.')
            handle = self._make_graphic_media(media_id, source, clip, width, height)
        source_id = handle.video_source if kind == 'video' else handle.audio_source
        if not source_id:
            raise ValueError(f'«{sequence_name}»: медиа «{handle.name}» не содержит {kind}-потока.')
        prototype = self.graph.occurrence_templates[kind]
        copied = self.graph.clone(self.graph.template, prototype, {
            ('ObjectURef', self.graph.media_master.get('ObjectUID')): handle.master_uid,
            ('ObjectRef', self.graph.source[kind].get('ObjectID')): source_id,
        })
        track_item = copied[prototype]
        sub = next(value for value in copied.values() if value.tag == 'SubClip')
        native_clip = next(value for value in copied.values()
                           if value.tag == ('VideoClip' if kind == 'video' else 'AudioClip'))
        self._set(sub, 'Name', str(clip.get('name') or handle.name))
        self._set(track_item, './ClipTrackItem/TrackItem/Start', start)
        self._set(track_item, './ClipTrackItem/TrackItem/End', start + duration)
        self._set(native_clip, './Clip/InPoint', source_in)
        self._set(native_clip, './Clip/OutPoint', source_in + duration)
        if kind == 'video':
            self._set(track_item, 'FrameRect', f'0,0,{handle.width},{handle.height}')
        else:
            stream = int(clip.get('audio_stream') or 0)
            if stream < 0:
                raise ValueError(f'«{sequence_name}»: некорректный индекс аудиопотока.')
            if stream:
                self.warnings.append(f'«{sequence_name}» / «{handle.name}»: '
                                     'выбор дополнительного аудиопотока требует проверки в Premiere.')
            self._adapt_audio_layout(copied.values(), handle.channels)
            self._set(native_clip, 'SecondaryIndex', stream)
        return track_item

    def _create_sequence(self, item_id: str, item: dict) -> None:
        name = str(item.get('name') or 'Sequence')
        sequence = item['kind']['Sequence']
        settings = sequence.get('settings') or {}
        width = max(1, int(settings.get('width') or 1920))
        height = max(1, int(settings.get('height') or 1080))
        frame_rate = self._period(settings.get('frame_rate'), 10594584000)
        sample_rate = max(1, int(settings.get('sample_rate') or 48000))
        clean = self.graph.clean
        old_bin = clean.by_uid[self.graph.sequence_bin.get('ObjectUID')]
        cloned = self.graph.clone(clean, old_bin)
        native_bin = cloned[old_bin]
        self._set(native_bin, './ProjectItem/Name', name)
        self.graph.append_bin(native_bin)
        native_seq = cloned[clean.by_uid[self.graph.sequence_template.get('ObjectUID')]]
        self._set(native_seq, 'Name', name)
        self._set(native_seq, './Node/Properties/MZ.Sequence.PreviewFrameSizeWidth', width)
        self._set(native_seq, './Node/Properties/MZ.Sequence.PreviewFrameSizeHeight', height)
        master = next(value for value in cloned.values() if value.tag == 'MasterClip')
        self._set(master, 'Name', name)
        video_source = next(value for value in cloned.values() if value.tag == 'VideoSequenceSource')
        audio_source = next(value for value in cloned.values() if value.tag == 'AudioSequenceSource')
        self.sequence_handles[item_id] = MediaHandle(master.get('ObjectUID'),
                                                     video_source.get('ObjectID'),
                                                     audio_source.get('ObjectID'),
                                                     name, width, height, 2)
        self.plans.append(SequencePlan(item_id, name, sequence, cloned, native_seq,
                                       width, height, frame_rate, sample_rate))

    def _populate_sequence(self, plan: SequencePlan) -> None:
        name, sequence, cloned, native_seq = (
            plan.name, plan.sequence, plan.cloned, plan.native_seq)
        clean = self.graph.clean
        width, height = plan.width, plan.height
        frame_rate, sample_rate = plan.frame_rate, plan.sample_rate
        sequence_end = 0
        linked: dict[str, list[str]] = {}
        if sequence.get('markers') or sequence.get('master_effects'):
            self.warnings.append(f'«{name}»: маркеры и мастер-эффекты не перенесены.')
        for kind in ('video', 'audio'):
            original = clean.by_id[self.graph.group_templates[kind].get('ObjectID')]
            group = cloned[original]
            self._set(group, './TrackGroup/FrameRate', frame_rate if kind == 'video'
                      else max(1, round(TICKS / sample_rate)))
            if kind == 'video':
                self._set(group, 'FrameRect', f'0,0,{width},{height}')
            track_refs = group.find('./TrackGroup/Tracks')
            if track_refs is None:
                raise ValueError('Premiere seed has no track list')
            track_refs.clear()
            fc_tracks = sequence.get(f'{kind}_tracks') or []
            for track_index, track in enumerate(fc_tracks):
                if (track.get('effects') or track.get('muted') or track.get('solo')
                        or track.get('locked') or track.get('enabled') is False):
                    self.warnings.append(f'«{name}» / {kind} {track_index+1}: '
                                         'эффекты и состояние дорожки не перенесены.')
                # Each FC track gets its own native object and (for audio)
                # component/panner graph, independent of the seed track count.
                original_track = clean.by_uid[self.graph.track_templates[kind].get('ObjectUID')]
                new_track = self.graph.clone(clean, original_track)[original_track]
                self._set(new_track, './ClipTrack/Track/Index', track_index)
                self._set(new_track, './ClipTrack/Track/ID', track_index + 1)
                for suffix in ('ClipItems', 'TransitionItems'):
                    self._set(new_track, f'./ClipTrack/{suffix}/Index', track_index)
                items = new_track.find('./ClipTrack/ClipItems/TrackItems')
                if items is None:
                    raise ValueError('Premiere seed lacks TrackItems')
                items.clear()
                ET.SubElement(track_refs, 'Track', {'Index': str(track_index),
                                                    'ObjectURef': new_track.get('ObjectUID')})
                clips = sorted(track.get('items') or [], key=lambda c: int(c.get('start') or 0))
                previous_end = 0
                for clip in clips:
                    if int(clip.get('start') or 0) < previous_end:
                        raise ValueError(f'«{name}»: клипы перекрываются на одной дорожке {kind} '
                                         f'{track_index + 1}; нативная запись такого перекрытия не поддерживается.')
                    native = self._make_clip(kind, clip, name, width, height, frame_rate)
                    ET.SubElement(items, 'TrackItem', {'Index': str(len(items)),
                                                      'ObjectRef': native.get('ObjectID')})
                    previous_end = int(clip.get('start') or 0) + int(clip.get('duration') or 0)
                    sequence_end = max(sequence_end, previous_end)
                    if clip.get('link') is not None:
                        linked.setdefault(str(clip['link']), []).append(native.get('ObjectID'))
                if track.get('transitions'):
                    self.warnings.append(f'«{name}» / {kind} {track_index+1}: переходы пока не перенесены '
                                         f'({len(track["transitions"])}).')
            self._set(group, './TrackGroup/NextTrackID', len(fc_tracks) + 1)
        # Linking is represented by the native Link/TrackItemGroup graph.
        links = native_seq.find('./PersistentGroupContainer/LinkContainer/Links')
        if links is not None:
            for members in linked.values():
                if len(members) < 2:
                    continue
                link = copy.deepcopy(next(el for el in self.graph.template.root if el.tag == 'Link'))
                link.set('ObjectID', self.graph.alloc())
                refs = link.find('./TrackItemGroup/TrackItems')
                refs.clear()
                for index, native_id in enumerate(members):
                    ET.SubElement(refs, 'TrackItem', {'Index': str(index), 'ObjectRef': native_id})
                self.graph.output.append(link)
                ET.SubElement(links, 'Link', {'Index': str(len(links)), 'ObjectRef': link.get('ObjectID')})
        for object_ in cloned.values():
            if object_.tag in ('VideoSequenceSource', 'AudioSequenceSource'):
                self._set(object_, 'OriginalDuration', max(1, sequence_end))
        self._set(native_seq, './Node/Properties/MZ.WorkOutPoint', max(1, sequence_end))

    def _check_sequence_cycles(self, aliases: dict[str, str]) -> None:
        graph: dict[str, set[str]] = {}
        for plan in self.plans:
            children = set()
            for track in (plan.sequence.get('video_tracks') or []) + (plan.sequence.get('audio_tracks') or []):
                for clip in track.get('items') or []:
                    item_id = self._item_key(clip.get('item'))
                    target = aliases.get(item_id, item_id)
                    if target in self.sequence_handles:
                        children.add(target)
            graph[plan.item_id] = children
        visited, visiting = set(), set()

        def visit(item_id: str) -> None:
            if item_id in visiting:
                raise ValueError('FilmCraft project contains cyclic nested sequences.')
            if item_id in visited:
                return
            visiting.add(item_id)
            for child in graph[item_id]:
                visit(child)
            visiting.remove(item_id)
            visited.add(item_id)

        for item_id in graph:
            visit(item_id)

    def _apply_shell_metadata(self) -> None:
        if self.shell_path is None:
            self.warnings.append('Использованы встроенные метаданные Premiere; '
                                 'версия может отличаться от установленной. Проверяйте результат в Premiere Pro.')
            return
        raw = self.shell_path.read_bytes()
        if raw.startswith(b'\x1f\x8b'):
            raw = gzip.decompress(raw)
        shell = ET.fromstring(raw)
        if shell.tag != 'PremiereData':
            raise ValueError('Пустая оболочка не является проектом Premiere.')
        for tag in ('MZ.BuildVersion.Created', 'MZ.BuildVersion.Modified'):
            source = shell.find('.//' + tag)
            dest = self.graph.output.find('.//' + tag)
            if source is not None and dest is not None and source.text:
                dest.text = source.text
        self.warnings.append('Из пустой оболочки скопированы только строки версии; '
                             'совместимость графа всё равно требует проверки в Premiere Pro.')

    def write(self, output: Path) -> list[str]:
        output = Path(output)
        self.output_path = output.absolute()
        for source in (self.fc_path, self.shell_path):
            if source is not None and same_file(output, source):
                raise ValueError('Результат не должен перезаписывать исходный проект или пустую оболочку.')
        sequences = [x for x in self.items.values() if 'Sequence' in x.get('kind', {})]
        if not sequences:
            raise ValueError('В FilmCraft проекте нет последовательностей.')
        for item in sequences:
            sequence = item['kind']['Sequence']
            for track in (sequence.get('video_tracks') or []) + (sequence.get('audio_tracks') or []):
                for clip in track.get('items') or []:
                    item_id = self._item_key(clip.get('item'))
                    end = int(clip.get('source_in') or 0) + int(clip.get('duration') or 0)
                    self.media_needed_span[item_id] = max(self.media_needed_span.get(item_id, 0), end)
        self._apply_shell_metadata()
        name = str(self.project.get('name') or self.fc_path.stem)
        self._set(self.graph.root_bin, './ProjectItem/Name', name)
        guid = self.graph.output.find('.//MZ.Project.GUID')
        if guid is not None:
            guid.text = str(uuid.uuid4())
        # Each project item is authored once, independently of clip counts.
        for item_id, item in self.items.items():
            if 'Media' in item.get('kind', {}) and self._media_path(item):
                self._make_media(item_id, item)
        for item_id, item in self.items.items():
            if 'Sequence' in item.get('kind', {}):
                self._create_sequence(item_id, item)
            elif 'Graphic' in item.get('kind', {}) and item_id not in self.media_needed_span:
                self.warnings.append(f'«{item.get("name", item_id)}»: '
                                     'неиспользуемый Graphic без клипа не добавлен в Premiere.')
            elif not ({'Media', 'Graphic'} & item.get('kind', {}).keys()):
                self.warnings.append(f'«{item.get("name", item_id)}»: '
                                     'неподдерживаемый тип элемента не добавлен в Premiere.')

        # Older FC exports encode a nested sequence as a Media item with no path.
        # Match it by name only when the sequence name is unambiguous.
        by_name: dict[str, list[str]] = {}
        for seq_id, handle in self.sequence_handles.items():
            by_name.setdefault(handle.name, []).append(seq_id)
            self.media[seq_id] = handle  # Also accept direct sequence item refs.
        nested_aliases = {}
        for item_id, item in self.items.items():
            if 'Media' in item.get('kind', {}) and not self._media_path(item):
                matches = by_name.get(str(item.get('name') or ''), [])
                if len(matches) == 1:
                    self.media[item_id] = self.sequence_handles[matches[0]]
                    nested_aliases[item_id] = matches[0]
                elif item_id not in self.media_needed_span:
                    self.warnings.append(f'«{item.get("name", "Media") }»: '
                                         'медиа без пути не добавлено в Premiere.')
        self._check_sequence_cycles(nested_aliases)
        for plan in self.plans:
            self._populate_sequence(plan)
        self.graph.remove_orphans()
        media_count = len(self.graph.output.findall('Media'))
        xml = ET.tostring(self.graph.output, encoding='utf-8', xml_declaration=True)
        try:
            ET.fromstring(xml)
        except ET.ParseError as exc:
            raise ValueError('Сгенерированный Premiere XML некорректен; файл не сохранён.') from exc
        payload = gzip.compress(xml, compresslevel=6, mtime=0)
        output.parent.mkdir(parents=True, exist_ok=True)
        temp_path = None
        created_assets: list[Path] = []
        try:
            # Exclusive creation prevents overwriting user files. If anything
            # fails before the .prproj is installed, remove only our new PNGs.
            for path, png in self.generated_assets.items():
                with path.open('xb') as stream:
                    created_assets.append(path)
                    stream.write(png)
            with tempfile.NamedTemporaryFile(mode='wb', dir=output.parent,
                                             prefix=f'.{output.stem}.', suffix='.tmp',
                                             delete=False) as stream:
                temp_path = Path(stream.name)
                stream.write(payload)
            os.replace(temp_path, output)
        except BaseException:
            for path in created_assets:
                path.unlink(missing_ok=True)
            raise
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
        self.warnings.insert(0, f'Созданы {len(sequences)} последовательностей и '
                                f'{media_count} медиа-объектов без заполненного эталона Premiere.')
        return self.warnings
