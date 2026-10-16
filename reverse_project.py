"""UI-independent workflow for the experimental FilmCraft → Premiere writer."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fcproj_to_prproj import NativeWriter, same_file


REPORT_TEXT = {
    'ru': {
        'title': 'Отчёт FilmCraft → Premiere',
        'input': 'Вход', 'reference': 'Эталон', 'shell': 'Оболочка',
        'output': 'Выход', 'result': 'Результат',
        'empty': 'Предупреждений нет.',
        'note': ('Экспериментальный writer не гарантирует, что Premiere Pro откроет '
                 'результат. Новые последовательности, дорожки, медиа, эффекты и '
                 'переходы не создаются.'),
        'media': 'Медиафайлы не копируются; при необходимости перепривяжите их в Premiere Pro.',
    },
    'en': {
        'title': 'FilmCraft → Premiere conversion report',
        'input': 'Input', 'reference': 'Reference', 'shell': 'Shell',
        'output': 'Output', 'result': 'Result',
        'empty': 'No warnings.',
        'note': ('This experimental writer cannot guarantee Premiere Pro will open the '
                 'output. It does not create new sequences, tracks, media, effects, or '
                 'transitions. Writer diagnostics below are currently in Russian.'),
        'media': 'Media files are not copied; relink them in Premiere Pro if needed.',
    },
}


class ReportWriteError(OSError):
    """The project was written, but its companion report could not be saved."""

    def __init__(self, output: Path, error: Exception):
        self.output = output
        super().__init__(str(error) or type(error).__name__)


def reverse_report_path(output: Path) -> Path:
    return output.with_name(output.stem + '_conversion_report.md')


def reverse_report_text(source: Path, reference: Path, shell: Path, output: Path,
                        warnings: list[str], language: str) -> str:
    words = REPORT_TEXT['en' if language == 'en' else 'ru']
    lines = [
        f'# {words["title"]}', '',
        f'- {words["input"]}: `{source.name}`',
        f'- {words["reference"]}: `{reference.name}`',
        f'- {words["shell"]}: `{shell.name}`',
        f'- {words["output"]}: `{output.name}`', '',
        words['note'], '',
        f'## {words["result"]}', '',
    ]
    lines += [f'- {message}' for message in warnings] if warnings else [words['empty']]
    lines += ['', words['media']]
    return '\n'.join(lines) + '\n'


def convert_reverse_project(source: Path, reference: Path, shell: Path,
                            output: Path, language: str = 'ru') -> tuple[Path, list[str]]:
    """Write a project and its report; return report and writer diagnostics."""
    report = reverse_report_path(output)
    if any(same_file(candidate, item)
           for candidate in (output, report)
           for item in (source, reference, shell)):
        raise ValueError('Результат или отчёт не может перезаписать входной проект или шаблон Premiere.')

    warnings = NativeWriter(source, reference, shell).write(output)
    # The project has already been written; report errors must be distinguishable.
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w', encoding='utf-8', dir=report.parent,
            prefix=f'.{report.stem}.', suffix='.tmp', delete=False,
        ) as temp:
            temp_path = Path(temp.name)
            temp.write(reverse_report_text(source, reference, shell, output,
                                           warnings, language))
        os.replace(temp_path, report)
    except Exception as exc:
        raise ReportWriteError(output, exc) from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return report, warnings
