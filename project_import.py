"""Format detection and queue conversion for project files (no Qt dependency)."""
from __future__ import annotations

import gzip
import json
import os
import re
import tempfile
import zlib
import xml.etree.ElementTree as ET
from pathlib import Path

from prproj_to_fcproj import Converter
from reverse_project import ReportWriteError, convert_reverse_project, reverse_report_path

PR_TO_FC = 'pr_to_fc'
FC_TO_PR = 'fc_to_pr'
SUPPORTED_EXTENSIONS = {'.prproj', '.fcproj', '.json', '.xml', '.txt'}


class ProjectTypeError(ValueError):
    """Rejected import; ``code`` can be translated by the desktop UI."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def detect_project_direction(path: Path) -> str:
    """Classify by format, not just suffix; never queue a shortcut profile."""
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ProjectTypeError('shortcut' if path.suffix.lower() == '.kys' else 'extension')
    if not path.is_file():
        raise ProjectTypeError('missing')
    with path.open('rb') as stream:
        header = stream.read(4096)
    trimmed = header.removeprefix(b'\xef\xbb\xbf').lstrip()
    compressed = header.startswith(b'\x1f\x8b')
    looks_xml = compressed or trimmed.startswith(b'<') or b'\x00' in header[:64]

    if trimmed.startswith((b'{', b'[')) or (path.suffix.lower() in {'.json', '.fcproj'} and not looks_xml):
        try:
            project = json.loads(path.read_text(encoding='utf-8-sig'))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ProjectTypeError('format') from exc
        if isinstance(project, dict) and project.get('format') == 'filmcraft.project':
            return FC_TO_PR
        if isinstance(project, dict) and project.get('format') == 'filmcraft-keyboard-shortcuts':
            raise ProjectTypeError('shortcut')
        raise ProjectTypeError('format')

    try:
        with path.open('rb') as stream:
            if compressed:
                with gzip.GzipFile(fileobj=stream) as decoded:
                    root = next(ET.iterparse(decoded, events=('start',)))[1]
            else:
                root = next(ET.iterparse(stream, events=('start',)))[1]
    except (ET.ParseError, StopIteration, gzip.BadGzipFile, EOFError, UnicodeError, zlib.error) as exc:
        # Premiere exports may be UTF-16 without a BOM (Converter accepts them).
        if b'\x00' in header[:64]:
            for encoding in ('utf-16-le', 'utf-16-be'):
                prefix = header.decode(encoding, errors='ignore')
                if re.search(r'(?:^|\?>)\s*<PremiereData(?:\s|>)', prefix.lstrip()):
                    return PR_TO_FC
        raise ProjectTypeError('format') from exc
    if root.tag == 'PremiereData':
        return PR_TO_FC
    if 'keyboard' in root.tag.lower() or root.tag.lower().endswith('kys'):
        raise ProjectTypeError('shortcut')
    raise ProjectTypeError('format')


def output_stem(path: Path) -> str:
    name = path.name
    if name.lower().endswith('.prproj.txt'):
        name = name[:-len('.prproj.txt')]
    elif path.suffix:
        name = path.stem
    name = re.sub(r'[^\w.() -]+', '_', name, flags=re.UNICODE).strip(' .')
    return name or 'Converted_Project'


def next_output_path(directory: Path, stem: str, suffix: str) -> Path:
    """Avoid replacing both a project and a report from an earlier run."""
    n = 1
    while True:
        name = stem if n == 1 else f'{stem}_{n}'
        candidate = directory / f'{name}{suffix}'
        report = reverse_report_path(candidate)
        if not (candidate.exists() or candidate.is_symlink()
                or report.exists() or report.is_symlink()):
            return candidate
        n += 1


REPORT_TEXT = {
    'ru': {
        'title': 'Отчёт конвертации Premiere Pro → FilmCraft',
        'input': 'Вход', 'output': 'Выход', 'sequences': 'Последовательностей',
        'clips': 'Клипов на таймлайнах', 'transitions': 'Переходов',
        'warnings': 'Предупреждения', 'empty': 'Предупреждений нет.',
        'media': 'Медиафайлы не копируются. Если они перемещены, перепривяжите их в FilmCraft.',
    },
    'en': {
        'title': 'Premiere Pro → FilmCraft conversion report',
        'input': 'Input', 'output': 'Output', 'sequences': 'Sequences',
        'clips': 'Timeline clips', 'transitions': 'Transitions',
        'warnings': 'Warnings', 'empty': 'No warnings.',
        'media': 'Media files are not copied. If they have moved, relink them in FilmCraft.',
    },
}


def forward_report_text(source: Path, output: Path, document: dict,
                        warnings: list[str], language: str) -> str:
    words = REPORT_TEXT['en' if language == 'en' else 'ru']
    sequences = [item['kind']['Sequence'] for item in document['project']['items'].values()
                 if 'Sequence' in item.get('kind', {})]
    tracks = [track for sequence in sequences
              for track in sequence.get('video_tracks', []) + sequence.get('audio_tracks', [])]
    clips = sum(len(track.get('items', [])) for track in tracks)
    transitions = sum(len(track.get('transitions', [])) for track in tracks)
    lines = [
        f'# {words["title"]}', '',
        f'- {words["input"]}: `{source.name}`',
        f'- {words["output"]}: `{output.name}`',
        f'- {words["sequences"]}: {len(sequences)}',
        f'- {words["clips"]}: {clips}',
        f'- {words["transitions"]}: {transitions}',
        f'- {words["warnings"]}: {len(warnings)}', '',
        f'## {words["warnings"]}', '',
    ]
    lines += [f'- {w}' for w in warnings] if warnings else [words['empty']]
    lines += ['', words['media']]
    return '\n'.join(lines) + '\n'


def convert_queued_project(record: dict, output_dir: Path,
                           language: str = 'ru') -> tuple[Path, int]:
    """Execute one preclassified queue item and write its sibling report."""
    source = Path(record['path'])
    direction = record['direction']
    if direction not in (PR_TO_FC, FC_TO_PR):
        raise ValueError(f'Unknown project direction: {direction}')
    if detect_project_direction(source) != direction:
        raise ValueError('Формат проекта изменился после добавления в очередь; удалите файл и добавьте его заново.')
    output_dir.mkdir(parents=True, exist_ok=True)
    if direction == PR_TO_FC:
        output = next_output_path(output_dir, output_stem(source), '.fcproj')
        converter = Converter(source, language=language)
        # The forward converter writes directly to the path it receives. Use a
        # temporary file so a failure cannot leave a partially written .fcproj.
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=output_dir, suffix='.fcproj', delete=False) as temp:
                temp_path = Path(temp.name)
            document = converter.convert(temp_path)
            os.replace(temp_path, output)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
        try:
            reverse_report_path(output).write_text(
                forward_report_text(source, output, document, converter.warnings, language),
                encoding='utf-8')
        except Exception as exc:
            raise ReportWriteError(output, exc) from exc
        return output, len(converter.warnings)
    shell_value = (record.get('shell') or '').strip()
    shell = Path(shell_value) if shell_value else None
    if shell is not None and not shell.is_file():
        raise ValueError('Указанная пустая оболочка Premiere не найдена.')
    output = next_output_path(output_dir, output_stem(source), '.prproj')
    _, messages = convert_reverse_project(source, output, language, shell=shell,
                                          graphic_mode=record.get('graphic_mode', 'native'))
    return output, len(messages)
