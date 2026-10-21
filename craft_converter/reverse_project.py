"""UI-independent workflow for direct FilmCraft → Premiere project writing."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .direct_fc_to_prproj import DirectWriter
from fcproj_to_prproj import same_file


REPORT_TEXT = {
    'ru': {
        'title': 'Отчёт FilmCraft → Premiere',
        'input': 'Вход', 'shell': 'Пустая оболочка (необязательно)',
        'output': 'Выход', 'result': 'Результат',
        'empty': 'Предупреждений нет.',
        'note': ('Экспериментальная прямая конвертация: медиа, дорожки и клипы '
                 'создаются из FilmCraft без заполненного Premiere-эталона. '
                 'Эффекты, переходы и особые параметры могут не переноситься. '
                 'Открытие результата в Premiere Pro необходимо проверить.'),
        'media': ('Исходные медиафайлы не копируются. Простой статичный Graphic-текст '
                  'переносится как нативный титр; при PNG fallback файлы сохраняются рядом '
                  'с проектом — переносите их вместе. Шрифты должны быть установлены в '
                  'Premiere; при необходимости перепривяжите исходные медиа.'),
    },
    'en': {
        'title': 'FilmCraft → Premiere conversion report',
        'input': 'Input', 'shell': 'Empty shell (optional)',
        'output': 'Output', 'result': 'Result',
        'empty': 'No warnings.',
        'note': ('Experimental direct conversion: media, tracks and clips are built '
                 'from FilmCraft without a populated Premiere reference. Effects, '
                 'transitions and special properties may not transfer. Verify the '
                 'result by opening it in Premiere Pro. Diagnostics below may be in Russian.'),
        'media': ('Original media files are not copied. Simple static Graphic text is '
                  'encoded as a native title; any fallback Graphic PNGs are saved beside '
                  'the project, so move them together. Install the source fonts in '
                  'Premiere and relink original media if needed.'),
    },
}


class ReportWriteError(OSError):
    """A project was written, but its companion report could not be saved."""

    def __init__(self, output: Path, error: Exception):
        self.output = output
        super().__init__(str(error) or type(error).__name__)


def reverse_report_path(output: Path) -> Path:
    return output.with_name(output.stem + '_conversion_report.md')


def reverse_report_text(source: Path, output: Path, warnings: list[str],
                        language: str, shell: Path | None = None) -> str:
    words = REPORT_TEXT['en' if language == 'en' else 'ru']
    lines = [
        f'# {words["title"]}', '',
        f'- {words["input"]}: `{source.name}`',
        f'- {words["output"]}: `{output.name}`',
    ]
    if shell is not None:
        lines.append(f'- {words["shell"]}: `{shell.name}`')
    lines += ['', words['note'], '', f'## {words["result"]}', '']
    lines += [f'- {message}' for message in warnings] if warnings else [words['empty']]
    lines += ['', words['media']]
    return '\n'.join(lines) + '\n'


def convert_reverse_project(source: Path, output: Path, language: str = 'ru',
                            shell: Path | None = None,
                            graphic_mode: str = 'native') -> tuple[Path, list[str]]:
    """Write a new project and its report; no populated Premiere project needed."""
    source, output = Path(source), Path(output)
    shell = Path(shell) if shell else None
    report = reverse_report_path(output)
    if any(same_file(candidate, item)
           for candidate in (output, report)
           for item in (source, shell) if item is not None):
        raise ValueError('Результат или отчёт не может перезаписать входной проект или пустую оболочку.')

    warnings = DirectWriter(source, shell, graphic_mode=graphic_mode).write(output)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w', encoding='utf-8', dir=report.parent,
            prefix=f'.{report.stem}.', suffix='.tmp', delete=False,
        ) as temp:
            temp_path = Path(temp.name)
            temp.write(reverse_report_text(source, output, warnings, language, shell))
        os.replace(temp_path, report)
    except Exception as exc:
        raise ReportWriteError(output, exc) from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return report, warnings
