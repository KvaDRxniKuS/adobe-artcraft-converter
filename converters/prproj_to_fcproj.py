#!/usr/bin/env python3
"""Direct, best-effort Premiere Pro (.prproj) -> FilmCraft (.fcproj) converter.

Uses only Python's standard library. Reads PremiereData XML, UTF-16 XML, or gzip-wrapped XML.
It does not invoke Premiere or export an intermediate FCP7 XML/OTIO file.
"""
from __future__ import annotations
import argparse, gzip, io, json, math, os, re, sys, xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

TICKS = 254_016_000_000
SCHEMA_VERSION = 15

WARNING_TEXT = {
 'ru': {
  'unknown_effect':'Не перенесён эффект «{display}» ({match}); требуется ручная проверка/аналог в FilmCraft.',
  'blur_uniform':'Gaussian Blur: Uniform Blur не имеет точного аналога; сохранено основное значение Blur.',
  'animated_param':'{display}: анимация параметра «{name}» пока не переносится; сохранено начальное значение.',
  'unmapped_param':'{display}: параметр «{name}» не сопоставлен; FilmCraft оставил ближайшее значение по умолчанию.',
  'lumetri_partial':'Lumetri: основные регуляторы и виньетка сопоставлены; LUT, кривые, Color Wheels, HSL Secondary и часть специальных данных Premiere не переносятся.',
  'impact_blur':'Gaussian Blur: сторонняя/вариантная реализация Impact Blur преобразована приблизительно (Amount → Blurriness); точное визуальное совпадение не гарантируется.',
  'offline_source':'Источник «{name}» не содержит обычный файл медиа; создана офлайн-заглушка.',
  'missing_media':'Медиа не найдено по записанному пути (FilmCraft предложит перепривязать): {path}',
  'bad_duration':'Пропущен клип с некорректной длительностью в {name}.',
  'missing_clip_source':'Не удалось найти источник клипа {name}; клип пропущен.',
  'bad_stream_index':'Некорректный SecondaryIndex аудиоисточника «{name}»; использован поток 0.',
  'unknown_transition':'Пропущен переход «{name}»: нет известного аналога.',
  'transition_not_at_cut':'Переход «{name}» не привязан к стыку клипов и пропущен.',
  'no_sequences':'В проекте не найдено ни одной последовательности.'
 },
 'en': {
  'unknown_effect':'Effect “{display}” ({match}) was not transferred; review it manually or choose a FilmCraft equivalent.',
  'blur_uniform':'Gaussian Blur: Uniform Blur has no exact equivalent; the main Blur value was preserved.',
  'animated_param':'{display}: animation for parameter “{name}” is not transferred yet; the initial value was preserved.',
  'unmapped_param':'{display}: parameter “{name}” was not mapped; FilmCraft keeps its nearest default value.',
  'lumetri_partial':'Lumetri: basic controls and vignette are mapped; LUTs, curves, Color Wheels, HSL Secondary, and some Premiere-specific data are not transferred.',
  'impact_blur':'Gaussian Blur: the third-party/variant Impact Blur implementation was approximated (Amount → Blurriness); exact visual matching is not guaranteed.',
  'offline_source':'Source “{name}” is not a regular media file; an offline placeholder was created.',
  'missing_media':'Media was not found at the recorded path (FilmCraft may ask you to relink it): {path}',
  'bad_duration':'Skipped a clip with invalid duration in {name}.',
  'missing_clip_source':'Could not find source for clip {name}; the clip was skipped.',
  'bad_stream_index':'Invalid audio source SecondaryIndex for “{name}”; stream 0 was used.',
  'unknown_transition':'Skipped transition “{name}”: no supported equivalent is known.',
  'transition_not_at_cut':'Transition “{name}” is not attached to a clip edit and was skipped.',
  'no_sequences':'No sequences were found in the project.'
 }
}

class Converter:
    def __init__(self, input_path: Path, media_root: str | None = None, language: str = 'ru'):
        self.input_path = input_path
        self.media_root = media_root
        self.language = 'en' if language == 'en' else 'ru'
        self.warnings: list[str] = []
        self.id_map: dict[str, ET.Element] = {}
        self.uid_map: dict[str, ET.Element] = {}
        self.media_by_source: dict[str, int] = {}
        self.native_media_to_item: dict[str, int] = {}
        # Premiere may model each selected audio stream as a separate Media object
        # even when all of them point at the same container file. Keep the per-file
        # stream table so FilmCraft can resolve each clip's audio_stream index.
        self.audio_streams_by_path: dict[str, dict[int, dict]] = {}
        self.items: dict[str, dict] = {}
        self.root_children: list[dict] = []
        self.next_id = 1
        self.name = input_path.stem
        self.tree = self._load_xml(input_path)
        for e in self.tree.iter():
            if e.get('ObjectID'): self.id_map[e.get('ObjectID')] = e
            if e.get('ObjectUID'): self.uid_map[e.get('ObjectUID')] = e

    def warn(self, key: str, **values) -> None:
        self.warnings.append(WARNING_TEXT[self.language][key].format(**values))

    def _load_xml(self, path: Path) -> ET.Element:
        data = path.read_bytes()
        if len(data) > 64 * 1024 * 1024:
            raise ValueError('Input exceeds 64 MiB safety limit')
        if data[:2] == b'\x1f\x8b':
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
                data = gz.read(64 * 1024 * 1024 + 1)
            if len(data) > 64 * 1024 * 1024:
                raise ValueError('Decompressed project exceeds 64 MiB safety limit')
        if len(data) > 64 * 1024 * 1024:
            raise ValueError('Decompressed project exceeds 64 MiB safety limit')
        if data.startswith((b'\xff\xfe', b'\xfe\xff')):
            data = data.decode('utf-16').encode('utf-8')
        elif not data.lstrip().startswith(b'<'):
            for enc in ('utf-8', 'utf-16-le', 'utf-16-be'):
                try:
                    decoded = data.decode(enc)
                    if '<PremiereData' in decoded: data = decoded.encode('utf-8'); break
                except UnicodeError: pass
        return ET.fromstring(data)

    @staticmethod
    def text(node: ET.Element | None, path: str, default: str | None = None) -> str | None:
        if node is None: return default
        found = node.find(path)
        if found is None or found.text is None: return default
        return found.text.strip()

    def resolve(self, ref: ET.Element | None) -> ET.Element | None:
        if ref is None: return None
        if ref.get('ObjectRef'): return self.id_map.get(ref.get('ObjectRef'))
        if ref.get('ObjectURef'): return self.uid_map.get(ref.get('ObjectURef'))
        return ref

    def child(self, node: ET.Element | None, *names: str) -> ET.Element | None:
        cur = node
        for name in names:
            if cur is None: return None
            cur = cur.find(name)
            if cur is not None and (cur.get('ObjectRef') or cur.get('ObjectURef')):
                cur = self.resolve(cur)
        return cur

    def refs(self, node: ET.Element | None, *names: str) -> list[ET.Element]:
        parent = self.child(node, *names)
        if parent is None: return []
        result = []
        for e in parent.iter():
            if e is parent: continue
            if e.get('ObjectRef') or e.get('ObjectURef'):
                target = self.resolve(e)
                if target is not None: result.append(target)
        # The graph can nest a list element under the final tag; unique refs keep order.
        seen, out = set(), []
        for e in result:
            key = e.get('ObjectID') or e.get('ObjectUID') or str(id(e))
            if key not in seen: seen.add(key); out.append(e)
        return out

    def alloc(self) -> int:
        n = self.next_id; self.next_id += 1; return n

    @staticmethod
    def tick_rate(period: int, fallback=(24000, 1001)) -> tuple[int, int]:
        if period <= 0: return fallback
        f = Fraction(TICKS, period)
        return f.numerator, f.denominator

    @staticmethod
    def ticks_period(rate: tuple[int, int]) -> int:
        return round(TICKS * rate[1] / rate[0])

    @staticmethod
    def param(value, variant='Float'):
        return {'value': {variant: value}}

    def effect_defaults(self, effect_id: str) -> dict:
        defaults = {
            'black_white': {},
            'gaussian_blur': {'blurriness': (0.0,'Float'), 'dimensions': (0,'Choice'), 'repeat_edge': (False,'Bool')},
            'brush_strokes': {'angle': (135.0,'Float'), 'size': (2.0,'Float'), 'length': (10.0,'Float'), 'density': (1.0,'Float'), 'randomness': (1.0,'Float'), 'surface': (0,'Choice'), 'blend': (0.0,'Float')},
            'noise': {'amount': (0.0,'Float'), 'color': (True,'Bool'), 'clip': (True,'Bool')},
            'lumetri': {'basic_on': (True,'Bool'), 'temperature': (0.0,'Float'), 'tint': (0.0,'Float'), 'exposure': (0.0,'Float'), 'contrast': (0.0,'Float'), 'highlights': (0.0,'Float'), 'shadows': (0.0,'Float'), 'whites': (0.0,'Float'), 'blacks': (0.0,'Float'), 'saturation': (100.0,'Float'), 'creative_on': (True,'Bool'), 'look': (0,'Choice'), 'look_intensity': (100.0,'Float'), 'faded_film': (0.0,'Float'), 'sharpen': (0.0,'Float'), 'vibrance': (0.0,'Float'), 'creative_sat': (100.0,'Float'), 'vignette_on': (True,'Bool'), 'vignette_amount': (0.0,'Float'), 'vignette_midpoint': (50.0,'Float'), 'vignette_roundness': (0.0,'Float'), 'vignette_feather': (50.0,'Float')},
        }
        return {k:self.param(v,typ) for k,(v,typ) in defaults.get(effect_id,{}).items()}

    def map_effect(self, component: ET.Element) -> dict | None:
        component_data = self.child(component, 'Component')
        if component_data is None: component_data = component
        display = self.text(component_data, 'DisplayName', 'Unknown effect') or 'Unknown effect'
        match = self.text(component_data, 'MatchName', self.text(component, 'MatchName', '')) or ''
        aliases = {
            'AE.ADBE Black & White': 'black_white',
            'AE.Impact_Blur_FX': 'gaussian_blur',
            'AE.ADBE Gaussian Blur 2': 'gaussian_blur',
            'AE.ADBE Brush Strokes': 'brush_strokes',
            'AE.ADBE Noise2': 'noise',
            'AE.ADBE Lumetri': 'lumetri',
        }
        effect_id = aliases.get(match)
        if effect_id is None:
            self.warn('unknown_effect', display=display, match=match or 'no MatchName')
            return None
        params = self.effect_defaults(effect_id)
        bypass=self.text(component_data,'Bypass','false')
        effect_enabled=bypass not in ('true','1')
        chain = component.find('Component')
        component_path = ('AudioComponent', 'Component') if component.tag.startswith('Audio') else ('Component',)
        param_container = self.child(component, *component_path, 'Params')
        if param_container is not None:
            for ref in param_container.iter('Param'):
                native = self.resolve(ref)
                if native is None: continue
                pid = self.text(native, 'ParameterID', '') or ''
                raw = self.text(native, 'StartKeyframe', '') or ''
                if not raw: continue
                fields = raw.split(',')
                if len(fields) < 2: continue
                value = fields[1].strip()
                # Supported, high-confidence native parameter mappings.
                map_key = None; variant = 'Float'; converted = None
                if effect_id == 'gaussian_blur' and pid == '82':
                    native_blur=self._number(value,0)
                    if native_blur != 0.0: map_key, variant, converted = 'blurriness','Float',native_blur
                elif effect_id == 'gaussian_blur' and match == 'AE.Impact_Blur_FX' and pid == '3':
                    map_key, variant, converted = 'blurriness','Float',self._number(value,0)
                elif effect_id == 'gaussian_blur' and pid == '5':
                    # FilmCraft blur is symmetric; retain the switch only in the report.
                    if value.lower() in ('true','false','0','1'): self.warn('blur_uniform')
                elif effect_id == 'brush_strokes' and pid in {'1','2','3','4','5','6','7'}:
                    names={'1':'angle','2':'size','3':'length','4':'density','5':'randomness','6':'surface','7':'blend'}
                    map_key=names[pid]
                    if pid=='6': variant, converted='Choice',int(self._number(value,0))
                    else: variant, converted='Float',self._number(value,0)
                elif effect_id == 'noise' and pid in {'1','2','3'}:
                    names={'1':'amount','2':'color','3':'clip'}; map_key=names[pid]
                    if pid=='1': variant, converted='Float',self._number(value,0)
                    elif pid=='2': variant, converted='Bool',value.lower() in ('1','true','color')
                    else: variant, converted='Bool',value.lower() in ('1','true')
                elif effect_id == 'lumetri':
                    lumetri_ids={'3':'basic_on','7':'temperature','8':'tint','11':'exposure','12':'contrast','13':'highlights','14':'shadows','15':'whites','16':'blacks','20':'saturation','23':'creative_on','26':'look_intensity','28':'faded_film','29':'sharpen','30':'vibrance','31':'creative_sat','50':'vignette_on','51':'vignette_amount','52':'vignette_midpoint','53':'vignette_roundness','54':'vignette_feather'}
                    map_key=lumetri_ids.get(pid)
                    if map_key:
                        default_type=params.get(map_key,{}).get('value',{}).keys()
                        variant=next(iter(default_type),'Float')
                        if variant=='Bool': converted=value.lower() in ('1','true')
                        elif variant=='Choice': converted=int(self._number(value,0))
                        else: converted=self._number(value,0)
                if map_key:
                    params[map_key] = self.param(converted,variant)
                    if self.text(native,'IsTimeVarying','false') in ('true','1'):
                        self.warn('animated_param', display=display, name=self.text(native,'Name',map_key))
                elif effect_id not in {'black_white','lumetri'} and pid not in {'8100','8040','8041','8140','8141','8240','9020','9040','9041','9042','5'}:
                    # Do not flood the report with implementation-only control widgets.
                    pname = self.text(native,'Name','') or ''
                    if pname and pname not in ('Controls','None','Error occurred'):
                        self.warn('unmapped_param', display=display, name=pname)
        if effect_id == 'lumetri':
            self.warn('lumetri_partial')
        if effect_id == 'gaussian_blur' and match == 'AE.Impact_Blur_FX':
            self.warn('impact_blur')
        return {'effect':effect_id,'enabled':effect_enabled,'params':params}

    @staticmethod
    def _number(s: str, default: float) -> float:
        try:
            x=float(s)
            return x if math.isfinite(x) and abs(x)<1e9 else default
        except Exception: return default

    @staticmethod
    def intrinsic_video(width: int, height: int) -> list[dict]:
        p=Converter.param
        return [
            {'effect':'motion','enabled':True,'params':{'anchor':p({'x':width/2,'y':height/2},'Vec2'),'anti_flicker':p(0.0),'position':p({'x':width/2,'y':height/2},'Vec2'),'rotation':p(0.0),'scale':p(100.0),'scale_width':p(100.0),'uniform_scale':p(True,'Bool')}},
            {'effect':'opacity','enabled':True,'params':{'blend':p(0,'Choice'),'opacity':p(100.0)}},
            {'effect':'time_remap','enabled':True,'params':{'speed':p(100.0)}},
        ]

    @staticmethod
    def intrinsic_audio() -> list[dict]:
        p=Converter.param
        return [
            {'effect':'volume','enabled':True,'params':{'bypass':p(False,'Bool'),'level':p(0.0)}},
            {'effect':'channel_volume','enabled':True,'params':{'bypass':p(False,'Bool'),'left':p(0.0),'right':p(0.0)}},
            {'effect':'panner','enabled':True,'params':{'balance':p(0.0)}},
        ]

    def media_source(self, source: ET.Element) -> ET.Element | None:
        media_ref = source.find('.//Media')
        return self.resolve(media_ref)

    @staticmethod
    def _media_path_key(media: ET.Element) -> str:
        path = (media.findtext('ActualMediaFilePath') or media.findtext('FilePath') or media.findtext('RelativePath') or '').strip()
        if path:
            return os.path.normpath(path.replace('\\\\', '/').replace('\\', '/')).casefold()
        return media.get('ObjectUID') or media.get('ObjectID') or ''

    def _audio_stream_metadata(self, audio: ET.Element | None) -> dict:
        period = int(self.text(audio, 'FrameRate', '5292000') or 5292000)
        sample_rate = max(1, round(TICKS / period))
        try:
            channels = len(json.loads(self.text(audio, 'AudioChannelLayout', '[]') or '[]'))
        except Exception:
            channels = 2
        return {'sample_rate': sample_rate, 'channels': max(1, channels), 'codec': 'Unknown (from Premiere project)', 'bits_per_sample': None}

    def index_audio_streams(self) -> None:
        """Build stream metadata and indices from Premiere's per-clip audio routing."""
        for clip in self.tree.iter('AudioClip'):
            source = self.child(clip, 'Clip', 'Source')
            media = self.media_source(source) if source is not None else None
            if media is None:
                continue
            try:
                stream_index = max(0, int(self.text(clip, 'SecondaryIndex', '0') or 0))
            except (TypeError, ValueError):
                stream_index = 0
            key = self._media_path_key(media)
            if not key:
                continue
            audio = self.resolve(media.find('AudioStream'))
            if audio is None:
                continue
            self.audio_streams_by_path.setdefault(key, {})[stream_index] = self._audio_stream_metadata(audio)

    def add_media(self, source: ET.Element, name: str) -> int:
        media = self.media_source(source)
        if media is None:
            key=source.get('ObjectID') or source.get('ObjectUID') or name
            if key in self.media_by_source: return self.media_by_source[key]
            item_id=self.alloc(); self.media_by_source[key]=item_id
            self.warn('offline_source', name=name)
            info={'name':name,'kind':'Movie','duration':0,'video':None,'audio_streams':[],'container':'','start_timecode':None,'file_size':None}
            media_obj={'media':{'File':{'path':''}},'info':info,'interpret':{'frame_rate':None,'par':None,'ignore_alpha':False,'invert_alpha':False},'mark_in':None,'mark_out':None,'markers':[],'offline':False,'proxy':None}
            self.items[str(item_id)]={'id':item_id,'name':name,'label':'Iris','kind':{'Media':media_obj}}
            self.root_children.append({'Item':item_id}); return item_id
        key=media.get('ObjectUID') or media.get('ObjectID') or name
        if key in self.media_by_source: return self.media_by_source[key]
        item_id=self.alloc(); self.media_by_source[key]=item_id
        path=(self.text(media,'ActualMediaFilePath') or self.text(media,'FilePath') or self.text(media,'RelativePath') or '').replace('\\\\','\\')
        if self.media_root and path:
            path=os.path.join(self.media_root,Path(path.replace('\\','/')).name)
        path=path.strip()
        vs=self.resolve(media.find('VideoStream')); au=self.resolve(media.find('AudioStream'))
        video=None; audio_streams=[]; duration=0
        if vs is not None:
            rect=self.text(vs,'FrameRect','0,0,1920,1080').split(',')
            try: w,h=int(rect[2])-int(rect[0]),int(rect[3])-int(rect[1])
            except Exception: w,h=1920,1080
            period=int(self.text(vs,'FrameRate','10594584000') or 10594584000)
            video={'width':max(1,w),'height':max(1,h),'frame_rate':{'num':self.tick_rate(period)[0],'den':self.tick_rate(period)[1]},'par':[1,1],'codec':'Unknown (from Premiere project)','pixel_format':'','color':{'matrix':'Bt709','transfer':'Srgb','primaries':'Bt709','range':'Full'},'has_alpha':False,'bitrate':None,'hdr':None}
            duration=max(duration,int(self.text(vs,'Duration','0') or 0))
        if au is not None:
            fallback_audio = self._audio_stream_metadata(au)
            file_streams = self.audio_streams_by_path.get(self._media_path_key(media), {})
            stream_count = max(file_streams, default=0) + 1
            audio_streams = [file_streams.get(index, fallback_audio) for index in range(stream_count)]
            duration=max(duration,int(self.text(au,'Duration','0') or 0))
        ext=Path(path.replace('\\','/')).suffix.lower()
        kind='AudioOnly' if ext in {'.wav','.mp3','.aif','.aiff','.m4a','.flac','.aac'} and video is None else ('Still' if ext in {'.png','.jpg','.jpeg','.tif','.tiff','.bmp','.gif','.webp'} else 'Movie')
        info={'name':name,'kind':kind,'duration':duration,'video':video,'audio_streams':audio_streams,'container':ext[1:].upper() if ext else '','start_timecode':None,'file_size':None}
        media_obj={'media':{'File':{'path':path}},'info':info,'interpret':{'frame_rate':None,'par':None,'ignore_alpha':False,'invert_alpha':False},'mark_in':None,'mark_out':None,'markers':[],'offline':False,'proxy':None}
        self.items[str(item_id)]={'id':item_id,'name':name,'label':'Iris','kind':{'Media':media_obj}}
        self.root_children.append({'Item':item_id})
        if path and not os.path.exists(path): self.warn('missing_media', path=path)
        return item_id

    def project_media(self):
        project=next((e for e in self.tree.iter() if e.tag=='Project' and e.get('ObjectID')),None)
        if project is None: raise ValueError('No Premiere Project object found')
        root=self.child(project,'RootProjectItem')
        if root is None: raise ValueError('Premiere project has no root bin')
        for leaf in self.refs(root,'ProjectItemContainer','Items'):
            if leaf.tag!='ClipProjectItem': continue
            name=self.text(leaf,'ProjectItem/Name') or self.text(leaf,'Name') or 'Imported media'
            if name=='': name='Imported media'
            master=self.child(leaf,'MasterClip')
            source=None
            if master is not None:
                for clip in self.refs(master,'Clips'):
                    if clip.tag in ('VideoClip','AudioClip'):
                        source=self.child(clip,'Clip','Source'); break
            if source is None: continue
            # Sequence project items are materialized in the sequence pass, not as file media.
            if self.child(source,'SequenceSource','Sequence') is not None: continue
            self.add_media(source,name)
        return project

    def make_sequence(self, node: ET.Element) -> tuple[int, dict]:
        name=self.text(node,'Name','Imported sequence') or 'Imported sequence'
        groups=[]
        groups_container=self.child(node,'TrackGroups')
        for tg in list(groups_container) if groups_container is not None else []:
            if tg.tag!='TrackGroup': continue
            group=self.child(tg,'Second')
            if group is not None: groups.append(group)
        vgroup=next((g for g in groups if g.tag=='VideoTrackGroup'),None)
        agroup=next((g for g in groups if g.tag=='AudioTrackGroup'),None)
        frame_period=int(self.text(vgroup,'TrackGroup','') or 0) if False else int(self.text(self.child(vgroup,'TrackGroup'),'FrameRate','10594584000') or 10594584000)
        fps=self.tick_rate(frame_period)
        audio_period=int(self.text(self.child(agroup,'TrackGroup'),'FrameRate','5292000') or 5292000)
        sample_rate=max(1,round(TICKS/audio_period))
        rect=(self.text(vgroup,'FrameRect','0,0,1920,1080') if vgroup is not None else '0,0,1920,1080').split(',')
        try: width,height=int(rect[2])-int(rect[0]),int(rect[3])-int(rect[1])
        except Exception: width,height=1920,1080
        width=max(1,width);height=max(1,height)
        sequence_id=self.alloc()
        video_tracks=[]; audio_tracks=[]; clip_native_map={}
        group_specs=[]
        for g,kind in ((vgroup,'Video'),(agroup,'Audio')):
            if g is None: continue
            tracks=self.refs(g,'TrackGroup','Tracks')
            for index,track_node in enumerate(tracks):
                track_id=self.alloc(); is_video=kind=='Video'; target_items=[]; transitions=[]
                native_clip_refs=self.refs(track_node,'ClipTrack','ClipItems','TrackItems')
                for native in native_clip_refs:
                    start=int(self.text(self.child(native,'ClipTrackItem','TrackItem'),'Start','0') or 0)
                    end=int(self.text(self.child(native,'ClipTrackItem','TrackItem'),'End','0') or 0)
                    if end<=start: self.warn('bad_duration', name=name); continue
                    sub=self.child(native,'ClipTrackItem','SubClip')
                    clip=self.child(sub,'Clip') if sub is not None else None
                    source=self.child(clip,'Clip','Source') if clip is not None else None
                    cname=self.text(sub,'Name',f'Clip {len(target_items)+1}') if sub is not None else f'Clip {len(target_items)+1}'
                    if source is None:
                        self.warn('missing_clip_source', name=cname); continue
                    native_media=self.media_source(source)
                    media_key=(native_media.get('ObjectUID') or native_media.get('ObjectID')) if native_media is not None else ''
                    item_id=self.media_by_source.get(media_key)
                    if item_id is None: item_id=self.add_media(source,cname)
                    source_in=int(self.text(self.child(clip,'Clip'),'InPoint','0') or 0)
                    source_out=int(self.text(self.child(clip,'Clip'),'OutPoint',str(source_in+end-start)) or (source_in+end-start))
                    duration=end-start
                    speed=(source_out-source_in)/duration if duration else 1.0
                    clip_id=self.alloc()
                    audio_stream=0
                    if not is_video and clip is not None:
                        raw_stream=self.text(clip,'SecondaryIndex','0') or '0'
                        try: audio_stream=max(0,int(raw_stream))
                        except ValueError:
                            self.warn('bad_stream_index', name=cname)
                    effects=self.intrinsic_video(width,height) if is_video else self.intrinsic_audio()
                    component_owner=self.child(native,'ClipTrackItem','ComponentOwner','Components')
                    if component_owner is not None:
                        chain=self.resolve(component_owner)
                        for component in self.refs(chain,'ComponentChain','Components'):
                            mapped=self.map_effect(component)
                            if mapped: effects.append(mapped)
                    clip_json={'id':clip_id,'item':item_id,'name':cname or 'Clip','label':'Iris','start':start,'duration':duration,'source_in':source_in,'speed':speed,'reverse':False,'enabled':True,'link':None,'group':None,'effects':effects,'markers':[],'gain_db':0.0,'frame_hold':None,'scale_to_frame':False,'essential':None,'multicam':None,'time_interpolation':'frameSampling','hold_filters':False,'field_options':None,'source_channels':[],'audio_stream':audio_stream}
                    target_items.append(clip_json);clip_native_map[native.get('ObjectID')]=clip_id
                target_items.sort(key=lambda x:x['start'])
                clip_ends={x['start']+x['duration']:x['id'] for x in target_items}
                clip_starts={x['start']:x['id'] for x in target_items}
                for nt in self.refs(track_node,'ClipTrack','TransitionItems','TrackItems'):
                    tnode=self.child(nt,'TransitionTrackItem')
                    tname=self.text(tnode,'MatchName','') or ''
                    tid={'AE.ADBE Cross Dissolve New':'cross_dissolve','AE.AE_Impact_Dissolve':'cross_dissolve','Cross Dissolve':'cross_dissolve','Constant Power':'constant_power','Constant Gain':'constant_gain','Exponential Fade':'exponential_fade'}.get(tname)
                    if not tid:
                        self.warn('unknown_transition', name=self.text(tnode,'DisplayName',tname)); continue
                    trstart=int(self.text(self.child(nt,'TransitionTrackItem','TrackItem'),'Start','0') or 0)
                    trend=int(self.text(self.child(nt,'TransitionTrackItem','TrackItem'),'End','0') or 0)
                    length=trend-trstart
                    offset=int(self.text(self.child(nt,'TransitionTrackItem'),'Alignment',str(length//2)) or length//2)
                    cut=trstart+offset
                    outgoing=clip_ends.get(cut) if self.text(self.child(nt,'TransitionTrackItem'),'HasOutgoingClip','true')=='true' else None
                    incoming=clip_starts.get(cut) if self.text(self.child(nt,'TransitionTrackItem'),'HasIncomingClip','true')=='true' else None
                    if not (outgoing or incoming):
                        self.warn('transition_not_at_cut', name=tname); continue
                    transitions.append({'id':self.alloc(),'effect':{'effect':tid,'enabled':True,'params':{}},'start':trstart,'duration':length,'from':outgoing,'to':incoming,'align':'CenterAtCut' if 0<offset<length else ('StartAtCut' if offset==0 else 'EndAtCut'),'reverse':False})
                tjson={'id':track_id,'kind':kind,'name':f'{kind} {index+1}','items':target_items,'transitions':transitions,'locked':False,'sync_lock':True,'enabled':True,'muted':False,'solo':False,'channels':'Stereo','volume_db':0.0,'pan':0.0,'effects':[]}
                (video_tracks if is_video else audio_tracks).append(tjson)
                group_specs.append((kind,index,target_items))
        # Preserve Premiere's explicit linked clip groups (including J/L cuts).
        native_to_json = clip_native_map
        link_id=1
        for link in self.refs(node,'PersistentGroupContainer','LinkContainer','Links'):
            members=[]
            for native_clip in self.refs(link,'TrackItemGroup','TrackItems'):
                out_id=native_to_json.get(native_clip.get('ObjectID'))
                if out_id is not None: members.append(out_id)
            if len(members)>1:
                for track in video_tracks+audio_tracks:
                    for clip in track['items']:
                        if clip['id'] in members: clip['link']=link_id
                link_id+=1
        seq={'settings':{'width':width,'height':height,'frame_rate':{'num':fps[0],'den':fps[1]},'par':[1,1],'sample_rate':sample_rate,'drop_frame':False,'preset':f'Premiere {width}x{height} {fps[0]/fps[1]:.3f} fps','audio_master':'Stereo','preview_codec':'ProRes 422','max_bit_depth':False,'max_render_quality':False,'working_space':'Rec. 709','color':{'working':'Rec709','wide_gamut':False,'auto_tone_map':True}},'video_tracks':video_tracks,'audio_tracks':audio_tracks,'markers':[],'mark_in':None,'mark_out':None,'work_area':None,'start_timecode':0,'master_volume_db':0.0,'master_effects':[]}
        return sequence_id, {'id':sequence_id,'name':name,'label':'Forest','kind':{'Sequence':seq}}

    def convert(self, output_path: Path) -> dict:
        self.index_audio_streams()
        self.project_media()
        sequence_nodes=[e for e in self.tree.iter() if e.tag=='Sequence' and (e.get('ObjectUID') or e.get('ObjectID'))]
        if not sequence_nodes: self.warn('no_sequences')
        seq_ids=[]
        for node in sequence_nodes:
            sid,item=self.make_sequence(node); self.items[str(sid)]=item; self.root_children.append({'Item':sid});seq_ids.append(sid)
        self.name=self.input_path.stem or 'Premiere import'
        settings={'renderer':'FilmCraft GPU Acceleration (wgpu)','video_display':'Timecode','audio_display_samples':True,'default_still_duration':5*TICKS,'default_transition_duration_frames':24,'default_audio_transition_duration':TICKS}
        doc={'format':'filmcraft.project','schema_version':SCHEMA_VERSION,'generator':'prproj_to_fcproj.py 0.2','project':{'name':self.name,'settings':settings,'root':{'id':0,'name':self.name,'children':self.root_children},'items':self.items,'next_id':self.next_id,'notes':'Imported directly from Premiere Pro .prproj. See sibling conversion report for effects and relinking notes.'},'view':{'open_sequences':seq_ids,'active_sequence':seq_ids[0] if seq_ids else None,'sequences':{}}}
        output_path.write_text(json.dumps(doc,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
        return doc

def main():
    ap=argparse.ArgumentParser(description='Directly convert Premiere Pro .prproj project data to FilmCraft .fcproj')
    ap.add_argument('input',type=Path)
    ap.add_argument('output',type=Path,nargs='?')
    ap.add_argument('--media-root',help='Optional directory: relink media by filename into this folder')
    ap.add_argument('--language',choices=('ru','en'),default='ru',help='Language for messages and report')
    args=ap.parse_args()
    en=args.language=='en'
    words={'title':'Premiere Pro → FilmCraft conversion report' if en else 'Отчёт конвертации Premiere Pro → FilmCraft',
      'input':'Input' if en else 'Вход','output':'Output' if en else 'Выход','sequences':'Sequences' if en else 'Последовательностей',
      'clips':'Timeline clips' if en else 'Клипов на таймлайнах','transitions':'Transitions' if en else 'Переходов',
      'schema':'FilmCraft schema' if en else 'Схема FilmCraft','limits':'Limitations and warnings' if en else 'Ограничения и предупреждения',
      'none':'No warnings.' if en else 'Предупреждений нет.',
      'note':'Project data is converted directly from `.prproj`; source media is not copied. If files are missing, relink them in FilmCraft. Mapped effects remain editable; unknown effects are listed above.' if en else 'Проект создаётся напрямую из структуры `.prproj`; исходные медиа не копируются. Если файлы не найдены, откройте проект в FilmCraft и перепривяжите медиа. Сопоставленные эффекты остаются редактируемыми; неизвестные эффекты перечислены выше.'}
    output=args.output or args.input.with_suffix('.fcproj')
    c=Converter(args.input,args.media_root,args.language)
    doc=c.convert(output)
    report=output.with_name(output.stem+'_conversion_report.md')
    seq_count=sum(1 for x in doc['project']['items'].values() if 'Sequence' in x['kind'])
    clip_count=sum(len(t['items']) for x in doc['project']['items'].values() if 'Sequence' in x['kind'] for t in x['kind']['Sequence']['video_tracks']+x['kind']['Sequence']['audio_tracks'])
    transition_count=sum(len(t['transitions']) for x in doc['project']['items'].values() if 'Sequence' in x['kind'] for t in x['kind']['Sequence']['video_tracks']+x['kind']['Sequence']['audio_tracks'])
    report.write_text(f'# {words["title"]}\n\n'
      f'- {words["input"]}: `{args.input.name}`\n- {words["output"]}: `{output.name}`\n- {words["sequences"]}: {seq_count}\n- {words["clips"]}: {clip_count}\n- {words["transitions"]}: {transition_count}\n- {words["schema"]}: {SCHEMA_VERSION}\n\n'
      f'## {words["limits"]}\n\n'
      + ('\n'.join(f'- {w}' for w in c.warnings) if c.warnings else '- '+words['none'])
      + '\n\n'+words['note']+'\n',encoding='utf-8')
    print(f'Created {output}')
    print(f'Created {report}')
    if en: print(f'{seq_count} sequence(s), {clip_count} clip instance(s), {transition_count} transition(s), {len(c.warnings)} warning(s).')
    else: print(f'{seq_count} последовательностей, {clip_count} клипов, {transition_count} переходов, {len(c.warnings)} предупреждений.')
    return 0
if __name__=='__main__':
    try: raise SystemExit(main())
    except Exception as exc:
        print(f'Conversion failed: {exc}',file=sys.stderr);raise
