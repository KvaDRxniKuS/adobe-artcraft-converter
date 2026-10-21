#!/usr/bin/env python3
"""Recognize AE Pixel Sorter 2 and emit an independent EffectCraft WASM effect.

This is deliberately NOT a generic .aex binary translator: it never loads or
executes Adobe code, the Windows installer, or the input .aex. Other Adobe SDK
plug-ins and different versions must be evaluated separately. EffectCraft's
published plug-in API v1 does not accept native After Effects DLLs.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

from effectcraft_pixel_sorter import MANIFEST, WASM, WASM_SHA256
from fcproj_to_prproj import same_file

MAX_AEX_BYTES = 64 * 1024 * 1024
_REQUIRED_EXPORTS = {'EffectMain', 'PluginDataEntryFunction'}
_REQUIRED_LABELS = (b'GG AEPixelSorter2\0', b'Sort by\0', b'Trigger\0',
                    b'Threshold\0', b'Feather Start\0', b'Feather End\0')


@dataclass(frozen=True)
class AexDetails:
    size: int
    sha256: str
    pe_timestamp: int
    exports: tuple[str, ...]
    labels: tuple[str, ...]


def _u16(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 2 > len(data):
        raise ValueError('У файла .aex повреждён заголовок PE.')
    return struct.unpack_from('<H', data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise ValueError('У файла .aex повреждён заголовок PE.')
    return struct.unpack_from('<I', data, offset)[0]


def _cstr(data: bytes, offset: int) -> str:
    if offset < 0 or offset >= len(data):
        raise ValueError('Ссылка на имя экспорта выходит за границы .aex.')
    end = data.find(b'\0', offset, min(offset + 128, len(data)))
    if end < 0:
        raise ValueError('Некорректное имя экспорта в .aex.')
    return data[offset:end].decode('ascii', errors='replace')


def inspect_aex(path: Path) -> AexDetails:
    """Bounded static PE inspection; no installer/DLL execution or extraction."""
    path = Path(path)
    with path.open('rb') as stream:
        data = stream.read(MAX_AEX_BYTES + 1)
    if len(data) > MAX_AEX_BYTES:
        raise ValueError('Файл .aex слишком велик для безопасного анализа (максимум 64 МБ).')
    if len(data) < 0x200 or data[:2] != b'MZ':
        raise ValueError('Ожидался 64-битный .aex (Windows DLL/PE), а не установщик или текст.')
    pe = _u32(data, 0x3c)
    if pe < 0x40 or pe > len(data) - 24 or data[pe:pe + 4] != b'PE\0\0':
        raise ValueError('Файл .aex не содержит корректной сигнатуры PE.')
    if _u16(data, pe + 4) != 0x8664 or not (_u16(data, pe + 22) & 0x2000):
        raise ValueError('Пока поддерживается только 64-битный .aex (PE DLL) AE Pixel Sorter 2.')
    section_count = _u16(data, pe + 6)
    optional_size = _u16(data, pe + 20)
    opt = pe + 24
    if not 1 <= section_count <= 96 or optional_size < 120 or opt + optional_size > len(data):
        raise ValueError('Некорректная таблица секций PE.')
    if _u16(data, opt) != 0x20b:
        raise ValueError('Пока поддерживаются только .aex с 64-битным заголовком PE32+.')
    timestamp = _u32(data, pe + 8)
    sec = opt + optional_size
    sections: list[tuple[int, int, int, int]] = []
    if sec + section_count * 40 > len(data):
        raise ValueError('Таблица секций выходит за границы .aex.')
    for idx in range(section_count):
        at = sec + idx * 40
        virtual_size = _u32(data, at + 8)
        virtual_address = _u32(data, at + 12)
        raw_size = _u32(data, at + 16)
        raw_offset = _u32(data, at + 20)
        if raw_size and raw_offset + raw_size > len(data):
            raise ValueError('Секция PE выходит за границы файла .aex.')
        sections.append((virtual_address, max(virtual_size, raw_size), raw_offset, raw_size))

    def rva_offset(rva: int, length: int) -> int:
        for address, size, raw_offset, raw_size in sections:
            if address <= rva and rva - address + length <= min(size, raw_size):
                result = raw_offset + rva - address
                if result + length <= len(data):
                    return result
        raise ValueError('Некорректный адрес таблицы экспорта .aex.')

    export_rva = _u32(data, opt + 112)
    export = rva_offset(export_rva, 40)
    names_count = _u32(data, export + 24)
    names_rva = _u32(data, export + 32)
    if names_count > 256:
        raise ValueError('Слишком много экспортов у .aex.')
    names = rva_offset(names_rva, names_count * 4)
    exports = tuple(_cstr(data, rva_offset(_u32(data, names + idx * 4), 1))
                    for idx in range(names_count))
    if not _REQUIRED_EXPORTS.issubset(exports) or any(label not in data for label in _REQUIRED_LABELS):
        raise ValueError('Это не распознанный AE Pixel Sorter 2. '
                         'Произвольные .aex нельзя автоматически превратить в работающий .wasm.')
    labels = tuple(label[:-1].decode('ascii') for label in _REQUIRED_LABELS)
    return AexDetails(len(data), hashlib.sha256(data).hexdigest(), timestamp, exports, labels)


def report_text(source: Path, output: Path, info: AexDetails, language: str = 'ru') -> str:
    stamp = dt.datetime.fromtimestamp(info.pe_timestamp, tz=dt.timezone.utc).strftime('%Y-%m-%d')
    if language == 'en':
        return (f'# .aex → EffectCraft: independent Pixel Sorter port\n\n'
                f'- Source: `{source.name}` ({info.size} bytes, x64 Windows PE DLL)\n'
                f'- PE build date (not proof of plug-in version): {stamp}\n'
                f'- Source SHA-256: `{info.sha256}`\n'
                f'- Result: `{output.name}` ({len(WASM)} bytes, EffectCraft WASM API v1)\n'
                f'- Effect id: `{MANIFEST["id"]}`, {len(MANIFEST["params"])} controls\n\n'
                'This is a **working independent pixel-sorting algorithm**, NOT a binary '
                'translation of AE Pixel Sorter 2. The provided .aex was read only for '
                'format recognition and names of controls; its code and license are not '
                'included, executed, or bypassed. The installer is never run.\n\n'
                'The effect sorts threshold-selected pixel runs in angle-based scanlines; '
                'it offers highlight/shadow selection, trigger/sort metrics, seed, offsets, '
                'feathering, smoothing and diagnostics. Its mathematics, defaults and UI '
                'behavior may differ from the original plug-in. External Source inputs, '
                'Resolution/Zoom controls and AE project presets are NOT transferred. '
                'No After Effects reference renders were supplied; visual parity is unverified.\n\n'
                'Load in EffectCraft desktop: **Effect → Load Effect Plug-in…** and select '
                f'`{output.name}`. It will appear in Stylize. Headless: '
                f'`effectcraft-cli exec effect.plugins.load \'{{"path":"{output.name}"}}\'`. '
                'EffectCraft itself was not available here; the WASM ABI and effect execution '
                'were tested independently. Compare with your Adobe render before relying on it.\n')
    return (f'# .aex → EffectCraft: независимый порт Pixel Sorter\n\n'
            f'- Вход: `{source.name}` ({info.size} байт, Windows PE DLL x64)\n'
            f'- Дата из PE (не подтверждает версию плагина): {stamp}\n'
            f'- SHA-256 входа: `{info.sha256}`\n'
            f'- Выход: `{output.name}` ({len(WASM)} байт, WASM API v1 EffectCraft)\n'
            f'- ID эффекта: `{MANIFEST["id"]}`, {len(MANIFEST["params"])} параметров\n\n'
            'Это **работающая независимая реализация сортировки пикселей**, а НЕ '
            'трансляция закрытого кода AE Pixel Sorter 2. Исходный .aex анализируется '
            'только для распознавания формата и названий параметров: его код/лицензия '
            'не копируются и не исполняются. Установщик НЕ запускался.\n\n'
            'Эффект сортирует выбранные порогом участки пикселей вдоль линий под углом; '
            'есть выбор Highlights/Shadows, метрики, смещение, seed, сглаживание, '
            'растушёвка и диагностические режимы. Алгоритм, диапазоны и поведение '
            'могут отличаться от оригинала. Внешний Source, Resolution/Zoom и '
            'настройки эффектов из проектов After Effects НЕ переносятся. '
            'Эталонного рендера AE пока нет: визуальное совпадение не проверено.\n\n'
            'Загрузка в EffectCraft (desktop): **Effect → Load Effect Plug-in…** → '
            f'`{output.name}`. Эффект появится в Stylize. '
            'Программы EffectCraft в этой среде нет; ABI и фактическая обработка кадров '
            'проверены отдельно. Сравните с рендером Adobe перед использованием.\n')


def convert_aex(source: Path, output: Path, *, language: str = 'ru') -> Path:
    """Safely write an independent .wasm and a sibling report; no overwrites."""
    source, output = Path(source), Path(output)
    if output.suffix.lower() != '.wasm':
        raise ValueError('Результат должен иметь расширение .wasm.')
    report = output.with_name(output.stem + '_conversion_report.md')
    if any(same_file(candidate, source) for candidate in (output, report)):
        raise ValueError('Результат не должен перезаписывать исходный .aex.')
    info = inspect_aex(source)
    if hashlib.sha256(WASM).hexdigest() != WASM_SHA256:
        raise RuntimeError('Встроенный EffectCraft WASM повреждён; конвертация прервана.')
    text = report_text(source, output, info, language)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or report.exists():
        raise FileExistsError('Файл результата или отчёта уже существует; выберите другое имя.')
    created = []
    try:
        with output.open('xb') as file:
            created.append(output)
            file.write(WASM)
        with report.open('x', encoding='utf-8') as file:
            created.append(report)
            file.write(text)
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return report


def output_stem(path: Path) -> str:
    name = path.name
    if name.lower().endswith('.txt'):
        name = name[:-4]
    if name.lower().endswith('.aex'):
        name = name[:-4]
    return name or 'pixel_sorter'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Experimental AE Pixel Sorter 2 → EffectCraft WASM port')
    parser.add_argument('input', type=Path, help='Recognized AE Pixel Sorter 2 .aex (also .aex.txt)')
    parser.add_argument('output', type=Path, nargs='?', help='New .wasm file (never overwritten)')
    parser.add_argument('--language', choices=('ru', 'en'), default='ru')
    args = parser.parse_args(argv)
    output = args.output or args.input.with_name(output_stem(args.input) + '_effectcraft.wasm')
    report = convert_aex(args.input, output, language=args.language)
    print(f'Создано: {output}\nОтчёт: {report}')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'Conversion failed: {exc}', file=sys.stderr)
        raise SystemExit(1) from exc
