#!/usr/bin/env python3
"""Inspect Windows AE .aex files; export implemented or validated measured effects.

Unknown DLLs without passing references get a diagnostic report, NEVER a fake
.wasm. The Adobe binary is read, not loaded, executed, decompiled or embedded.
A useful effect needs an independently coded renderer or measured model.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

from craft_converter.aex_metadata import AEEffectIdentity, read_pipl_identities
from craft_converter.ae_profile import load_ae_profile, profile_report
from craft_converter.ae_values import load_ae_settings, select_deep_glow_defaults, settings_report
from craft_converter.deep_glow_bounds import SCRIPT as BOUNDS_SCRIPT
from craft_converter.deep_glow_defaults import customized_wasm
from craft_converter.effectcraft_pixel_sorter import MANIFEST, WASM, WASM_SHA256
from craft_converter.effectcraft_deep_glow import (MANIFEST as GLOW_MANIFEST, WASM as GLOW_WASM,
                                   WASM_SHA256 as GLOW_SHA256)
from craft_converter.measured_port import (
    CHECK_AFTER, CHECK_INPUT, TRAIN_AFTER, TRAIN_INPUT, ReferenceError,
    build_port as build_colour_port, failure_report as colour_failure_report,
    fit as fit_colour_references, prepare_charts, report_text as colour_report_text,
)
from craft_converter.measured_beam import (
    build_port as build_line_port, failure_report as line_failure_report,
    fit as fit_line_references, report_text as line_report_text,
)
from converters.fcproj_to_prproj import same_file

MAX_AEX_BYTES = 64 * 1024 * 1024  # Limit untrusted input size, not plug-in identity.
_EFFECT_EXPORTS = {'EffectMain', 'PluginDataEntryFunction'}
_PIXEL_LABELS = (b'GG AEPixelSorter2\0', b'Sort by\0', b'Trigger\0',
                 b'Threshold\0', b'Feather Start\0', b'Feather End\0')
_GLOW_LABELS = (b'Deep Glow 2\0', b'Deep Glow\0', b'Radius\0',
                b'Exposure\0', b'Threshold\0', b'Blend Mode\0')
_PORTS = {
    'pixel_sorter': (MANIFEST, WASM, WASM_SHA256),
    'deep_glow': (GLOW_MANIFEST, GLOW_WASM, GLOW_SHA256),
}


class UnsupportedAexError(ValueError):
    """Static inspection succeeded but this effect has no working WASM port."""

    def __init__(self, report: Path):
        self.report = report
        super().__init__(f'Нет реализации эффекта для этого .aex; анализ: {report}')


@dataclass(frozen=True)
class AexDetails:
    size: int
    sha256: str
    pe_timestamp: int
    exports: tuple[str, ...]
    labels: tuple[str, ...]
    architecture: str
    family: str | None
    pipl_effects: tuple[AEEffectIdentity, ...] = ()


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
    """Safely inspect a PE effect DLL of any identity, without running it."""
    path = Path(path)
    with path.open('rb') as stream:
        data = stream.read(MAX_AEX_BYTES + 1)
    if len(data) > MAX_AEX_BYTES:
        raise ValueError('Файл .aex слишком велик для безопасного анализа (максимум 64 МБ).')
    if len(data) < 0x200 or data[:2] != b'MZ':
        raise ValueError('Ожидался Windows .aex (PE DLL), а не установщик или текст.')
    pe = _u32(data, 0x3c)
    if pe < 0x40 or pe > len(data) - 24 or data[pe:pe + 4] != b'PE\0\0':
        raise ValueError('Файл .aex не содержит корректной сигнатуры PE.')
    machine = _u16(data, pe + 4)
    if not (_u16(data, pe + 22) & 0x2000):
        raise ValueError('Ожидался плагин .aex (PE DLL), а не приложение/установщик.')
    section_count = _u16(data, pe + 6)
    optional_size = _u16(data, pe + 20)
    opt = pe + 24
    if not 1 <= section_count <= 96 or opt + optional_size > len(data):
        raise ValueError('Некорректная таблица секций PE.')
    magic = _u16(data, opt)
    if magic not in (0x10b, 0x20b) or (machine == 0x8664 and magic != 0x20b) or (
            machine == 0x14c and magic != 0x10b):
        raise ValueError('Некорректная комбинация архитектуры и заголовка PE.')
    directory_offset = 112 if magic == 0x20b else 96
    if optional_size < directory_offset + 8:
        raise ValueError('Таблица адресов PE обрезана.')
    architecture = {0x8664: 'x64', 0x14c: 'x86', 0xaa64: 'ARM64'}.get(
        machine, f'machine 0x{machine:04x}')
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

    export_rva = _u32(data, opt + directory_offset)
    exports: tuple[str, ...] = ()
    if export_rva:
        export = rva_offset(export_rva, 40)
        names_count = _u32(data, export + 24)
        names_rva = _u32(data, export + 32)
        # Bounded scan even if the DLL claims billions of export names.
        if names_count:
            scan_count = min(names_count, 256)
            names = rva_offset(names_rva, scan_count * 4)
            exports = tuple(_cstr(data, rva_offset(_u32(data, names + idx * 4), 1))
                            for idx in range(scan_count))
    pipl_effects = ()
    if optional_size >= directory_offset + 24:
        pipl_effects = read_pipl_identities(
            data, _u32(data, opt + directory_offset + 16),
            _u32(data, opt + directory_offset + 20), rva_offset)
    exported = _EFFECT_EXPORTS.issubset(exports)
    family = None
    labels: tuple[str, ...] = ()
    if exported and all(label in data for label in _PIXEL_LABELS):
        family = 'pixel_sorter'
        labels = tuple(label[:-1].decode('ascii') for label in _PIXEL_LABELS)
    elif exported and all(label in data for label in _GLOW_LABELS):
        family = 'deep_glow'
        labels = tuple(label[:-1].decode('ascii') for label in _GLOW_LABELS)
    if pipl_effects and family:
        # If a DLL declares an identity, do not export a known port merely
        # because some unrelated string in a multi-effect DLL mentions it.
        names, matches = {
            'pixel_sorter': ({'ae pixel sorter 2', 'pixel sorter 2'},
                             {'GG AEPixelSorter2'}),
            'deep_glow': ({'deep glow', 'deep glow 2'}, {'PEDG'}),
        }[family]
        if not any(effect.name.casefold() in names and
                   (effect.match_name is None or effect.match_name in matches)
                   for effect in pipl_effects):
            family, labels = None, ()
    return AexDetails(len(data), hashlib.sha256(data).hexdigest(), timestamp,
                      exports, labels, architecture, family, pipl_effects)


def pipl_report_line(info: AexDetails, language: str) -> str:
    """Separate declared PiPL identity from unverified parameter UI/behaviour."""
    if info.pipl_effects:
        effects = '; '.join(f'{e.name} [{e.category or "?"}; {e.match_name or "?"}]'
                            for e in info.pipl_effects)
    else:
        effects = 'not found' if language == 'en' else 'не обнаружены'
    key = 'PiPL identity (name [category; match name])' if language == 'en' else (
        'PiPL (имя [категория; match name])')
    return f'- {key}: {effects}\n'


def unported_report_text(source: Path, info: AexDetails, language: str = 'ru') -> str:
    entrypoints = ', '.join(name for name in ('EffectMain', 'PluginDataEntryFunction')
                            if name in info.exports) or 'none'
    if language == 'en':
        return (f'# .aex analysis — no WASM created\n\n'
                f'- Input: `{source.name}` ({info.size} bytes, PE {info.architecture})\n'
                f'- SHA-256: `{info.sha256}`\n'
                f'- Export names scanned: {len(info.exports)}; AE entry points: {entrypoints}\n'
                f'{pipl_report_line(info, language)}\n'
                'PiPL describes effect identity, not the render algorithm or parameter UI. '
                'Blur shape, per-parameter hard/soft bounds, slider vs numeric field, '
                'group hierarchy and keyframe/curve capabilities cannot be verified from '
                'this static DLL inspection. They require an AE-host parameter inventory or '
                'user-supplied reference; they are not guessed here.\n\n'
                'The Windows DLL was inspected statically and was NOT executed. '
                'This is not one of the independently implemented effects. '
                'EffectCraft cannot run After Effects binary code; simply lifting the '
                'identity restriction or renaming this DLL as .wasm would produce a '
                'non-working file. No WASM was written.\n\n'
                'For pixel-local colour effects, try the local reference wizard: generate two '
                'charts with --prepare-reference, render both in AE, then use --reference-dir. '
                'A validated fixed-setting colour LUT may be exported. For straight glowing '
                'beams on an opaque black background, paired AE renders at two sizes can be '
                'tested with --reference-model line --reference-dir. These are limited model '
                'families, not a general DLL-to-WASM translation; other spatial effects need '
                'their own reference-driven model and independent validation.\n')
    return (f'# Анализ .aex — WASM не создан\n\n'
            f'- Вход: `{source.name}` ({info.size} байт, PE {info.architecture})\n'
            f'- SHA-256: `{info.sha256}`\n'
            f'- Имен экспортов проверено: {len(info.exports)}; точки входа AE: {entrypoints}\n'
            f'{pipl_report_line(info, language)}\n'
            'PiPL содержит идентификатор эффекта, но не алгоритм и не полную схему '
            'параметров. Форма размытия, жёсткие/мягкие границы, тип поля или ползунка, '
            'группы и доступность ключевых кадров/кривых не определяются надёжно по '
            'такому статическому анализу DLL. Нужна инвентаризация через AE или '
            'данные пользователя; конвертер не угадывает их.\n\n'
            'Windows DLL исследована статически и НЕ запускалась. Для этого эффекта пока '
            'нет отдельной реализации. EffectCraft не исполняет код плагинов After Effects: '
            'снятие проверки имени или переименование в .wasm не создаст рабочий эффект. '
            'Файл WASM не создан.\n\n'
            'Для попиксельного цветового эффекта можно попробовать локальный мастер: '
            'создайте две картинки (--prepare-reference), обработайте их в AE и передайте '
            '--reference-dir. После проверки он может выдать цветовую 3D-таблицу для одних '
            'настроек. Для прямого светящегося луча на непрозрачном чёрном фоне можно '
            'проверить пару рендеров AE разного размера: --reference-model line --reference-dir. '
            'Это ограниченные семейства моделей, а не перевод любой DLL в WASM; для иных '
            'пространственных эффектов нужна другая модель по эталонам и независимая проверка.\n')


def bounds_script_path(output: Path) -> Path:
    """Companion script for applying Grow Bounds before Deep Glow."""
    return output.with_name(output.stem + '_apply_with_bounds.jsx')


def deep_glow_report_text(source: Path, output: Path, info: AexDetails,
                          language: str = 'ru') -> str:
    stamp = dt.datetime.fromtimestamp(info.pe_timestamp, tz=dt.timezone.utc).strftime('%Y-%m-%d')
    if language == 'en':
        return (f'# .aex → EffectCraft: independent multi-scale glow effect\n\n'
                f'- Input: `{source.name}` ({info.size} bytes, PE {info.architecture})\n'
                f'- PE build date (not an exact product version): {stamp}\n'
                f'- SHA-256: `{info.sha256}`\n'
                f'- Output: `{output.name}` ({len(GLOW_WASM)} bytes, WASM API v1)\n'
                f'- Effect id: `{GLOW_MANIFEST["id"]}`; version {GLOW_MANIFEST["version"]}; '
                f'{len(GLOW_MANIFEST["params"])} controls\n'
                f'{pipl_report_line(info, language)}\n'
                'This **working independent multi-scale bloom** is NOT the original '
                'Deep Glow 2 binary or an exact reimplementation. The supplied .aex '
                'was inspected for identity and public UI labels only; no Adobe code, '
                'licensing routines or installer was run, extracted or embedded.\n\n'
                'The effect selects highlights by luminance and soft threshold, blurs '
                'them at multiple radii (a small-scale Gaussian and a Gaussian-like '
                'three-box approximation for larger scales), then blends light back '
                'using exposure, spread, optional tint and alpha expansion. Its rendering, '
                'GPU features, controls, presets and look may differ substantially from '
                'AE Deep Glow 2. Radius 256 is only the slider endpoint: type a larger '
                'number (up to our chosen 1e9 hard maximum; API v1 requires a finite '
                'one). The internal effective blur radius saturates at 16 times the '
                'longest frame dimension, rather than clipping at 256; beyond that '
                'the image no longer changes. These settings '
                'describe our port, NOT values extracted from the original .aex. '
                'EffectCraft v1 has flat plug-in controls (no custom parameter groups '
                'or curve widgets), but ordinary plug-in properties can be keyframed. '
                'No paired After Effects reference frames were supplied: '
                'visual parity is unverified.\n\n'
                '**Footage bounds:** API v1 renders an in-place frame no larger than its input. '
                'The WASM alone cannot draw outside the source footage rectangle. Use the '
                f'companion `{bounds_script_path(output).name}` in EffectCraft (File → Scripts '
                '→ Run Script File…) after loading the WASM: select footage layer(s), and it '
                'inserts built-in Grow Bounds BEFORE Deep Glow. The padding follows Radius '
                'with an expression. Applying the plug-in directly still clips at the source '
                'edge. For very large layers/radii, the 4,000-pixel host setting and this '
                'port’s 9M-pixel render budget can still limit expansion; use a smaller '
                'source/comp-sized precomp or a host change. The script has not been tested '
                'in the EffectCraft desktop UI.\n\n'
                'Quit EffectCraft before replacing the earlier port: plug-ins with the '
                'same effect id cannot be loaded twice in one session. Keep only the new '
                'version in any auto-load folder, restart EffectCraft desktop and use '
                f'Effect → Load Effect Plug-in… → `{output.name}`. Find '
                '"Deep Glow (independent port)" in Stylize. Please check this version '
                'in the app; ABI and rendering were tested in Node.js and Wasmtime.\n')
    return (f'# .aex → EffectCraft: независимое многомасштабное свечение\n\n'
            f'- Вход: `{source.name}` ({info.size} байт, PE {info.architecture})\n'
            f'- Дата PE (не точная версия продукта): {stamp}\n'
            f'- SHA-256: `{info.sha256}`\n'
            f'- Выход: `{output.name}` ({len(GLOW_WASM)} байт, WASM API v1)\n'
            f'- ID эффекта: `{GLOW_MANIFEST["id"]}`; версия {GLOW_MANIFEST["version"]}; '
            f'{len(GLOW_MANIFEST["params"])} параметров\n'
            f'{pipl_report_line(info, language)}\n'
            'Это **работающий самостоятельный многомасштабный bloom**, а НЕ бинарник '
            'Deep Glow 2 и не точная копия его алгоритма. Исходный .aex исследован '
            'только для определения типа и видимых названий настроек; код, лицензия '
            'и установщик не извлекались и не исполнялись.\n\n'
            'Эффект выделяет светлые участки по яркости/мягкому порогу, применяет '
            'гауссово размытие для малых радиусов и плавное приближение тремя проходами '
            'для больших, затем смешивает свечение со слоем. Есть радиус, экспозиция, '
            'распространение, окраска и расширение альфа-канала. GPU-функции, настройки, '
            'пресеты и итоговая картинка могут значительно отличаться от оригинала. '
            '256 — край ползунка Radius, а не предел для числового поля: '
            'можно ввести больше (до выбранной нами границы 1e9: API v1 требует '
            'конечного максимума). '
            'Эффективный радиус рендера насыщается на 16-кратной длинной стороне '
            'кадра: дальше результат не меняется (не обрезается на 256). Это свойства '
            'нашего порта, НЕ извлечённые из исходного .aex. В API v1 параметры '
            'плагина плоские (без вложенных групп и редактора кривой), но обычные '
            'параметры поддерживают ключевые кадры. Парных эталонных кадров AE нет: '
            'совпадение не подтверждено.\n\n'
            '**Границы футажа:** WASM API v1 работает в исходном буфере и сам НЕ может '
            'расширить слой. Для ореола за пределами исходника после загрузки WASM '
            'выберите слой(и) и запустите в EffectCraft через File → Scripts → '
            f'Run Script File… файл `{bounds_script_path(output).name}`. Он ставит штатный '
            'Grow Bounds ПЕРЕД Deep Glow и привязывает его размер к Radius выражением. '
            'Если добавить один только WASM через меню эффектов, граница останется. '
            'Для больших исходников и радиусов расширение может ограничиваться '
            'диапазоном Grow Bounds (4000 px) и бюджетом порта (9 млн пикселей); '
            'может понадобиться меньший исходник/прекомпозиция размером с композицию '
            'или изменение самого EffectCraft. Скрипт не проверен в реальном '
            'настольном EffectCraft.\n\n'
            'Перед заменой старой версии закройте EffectCraft: два плагина с одним ID '
            'нельзя загрузить в одной сессии. Оставьте в папке автозагрузки только новый '
            'файл, перезапустите EffectCraft и выберите Effect → Load Effect Plug-in… → '
            f'`{output.name}`; в Stylize найдите "Deep Glow (independent port)". '
            'Проверьте эту версию в приложении: ABI и рендер проверены в Node.js и Wasmtime.\n')


def report_text(source: Path, output: Path, info: AexDetails, language: str = 'ru') -> str:
    if info.family == 'deep_glow':
        return deep_glow_report_text(source, output, info, language)
    if info.family != 'pixel_sorter':
        return unported_report_text(source, info, language)
    stamp = dt.datetime.fromtimestamp(info.pe_timestamp, tz=dt.timezone.utc).strftime('%Y-%m-%d')
    if language == 'en':
        return (f'# .aex → EffectCraft: independent Pixel Sorter port\n\n'
                f'- Source: `{source.name}` ({info.size} bytes, {info.architecture} Windows PE DLL)\n'
                f'- PE build date (not proof of plug-in version): {stamp}\n'
                f'- Source SHA-256: `{info.sha256}`\n'
                f'- Result: `{output.name}` ({len(WASM)} bytes, EffectCraft WASM API v1)\n'
                f'- Effect id: `{MANIFEST["id"]}`, {len(MANIFEST["params"])} controls\n'
                f'{pipl_report_line(info, language)}\n'
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
            f'- Вход: `{source.name}` ({info.size} байт, Windows PE DLL {info.architecture})\n'
            f'- Дата из PE (не подтверждает версию плагина): {stamp}\n'
            f'- SHA-256 входа: `{info.sha256}`\n'
            f'- Выход: `{output.name}` ({len(WASM)} байт, WASM API v1 EffectCraft)\n'
            f'- ID эффекта: `{MANIFEST["id"]}`, {len(MANIFEST["params"])} параметров\n'
            f'{pipl_report_line(info, language)}\n'
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


def convert_aex(source: Path, output: Path, *, language: str = 'ru',
                ae_profile: Path | None = None, ae_values: Path | None = None,
                reference_dir: Path | None = None, reference_model: str = 'colour') -> Path:
    """Export known ports or a validated, fixed-setting colour/line model."""
    if reference_model not in ('colour', 'line'):
        raise ValueError('Unknown reference model (choose colour or line).')
    if reference_model == 'line' and reference_dir is None:
        raise ValueError('Line generator fitting requires --reference-dir and AE PNGs.')
    source, output = Path(source), Path(output)
    ae_profile = Path(ae_profile) if ae_profile is not None else None
    ae_values = Path(ae_values) if ae_values is not None else None
    reference_dir = Path(reference_dir) if reference_dir is not None else None
    if output.suffix.lower() != '.wasm':
        raise ValueError('Результат должен иметь расширение .wasm.')
    conversion_report = output.with_name(output.stem + '_conversion_report.md')
    analysis_report = output.with_name(output.stem + '_aex_analysis.md')
    script = bounds_script_path(output)
    originals = [path for path in (source, ae_profile, ae_values) if path is not None]
    if reference_dir is not None:
        originals.extend(reference_dir / filename for filename in
                         (TRAIN_INPUT, TRAIN_AFTER, CHECK_INPUT, CHECK_AFTER))
    if any(same_file(candidate, original)
           for candidate in (output, conversion_report, analysis_report, script)
           for original in originals):
        raise ValueError('Результат не должен перезаписывать исходный .aex, профиль или кадры AE.')
    info = inspect_aex(source)
    report = conversion_report if reference_dir is not None or info.family in _PORTS else analysis_report
    script = script if reference_dir is None and info.family == 'deep_glow' else None
    if (output.exists() or report.exists() or (script is not None and script.exists())
            or (reference_dir is not None and analysis_report.exists())):
        raise FileExistsError('Файл результата, отчёта или скрипта уже существует; выберите другое имя.')
    profile = load_ae_profile(ae_profile, info.pipl_effects) if ae_profile else None
    if reference_dir is not None:
        if ae_values:
            raise ValueError('Снимок чисел Deep Glow нельзя совмещать с измеренной моделью по PNG.')
        if 'EffectMain' not in info.exports and not info.pipl_effects:
            raise ReferenceError('В DLL не найден EffectMain или AE PiPL; нужен действующий .aex эффекта.')
        model = ((fit_line_references, build_line_port, line_failure_report, line_report_text)
                 if reference_model == 'line' else
                 (fit_colour_references, build_colour_port,
                  colour_failure_report, colour_report_text))
        fit_model, build_model, failure_text, success_text = model
        fitted = fit_model(reference_dir, info.sha256)
        output.parent.mkdir(parents=True, exist_ok=True)
        if not fitted.accepted:
            text = failure_text(info, fitted, language)
            if profile:
                text += '\n' + profile_report(profile, language)
            with analysis_report.open('x', encoding='utf-8') as file:
                file.write(text)
            raise UnsupportedAexError(analysis_report)
        # One DLL may expose several effects; the PNGs cannot identify which
        # one the user actually applied inside AE. Avoid claiming the first PiPL.
        effect_name = (info.pipl_effects[0].name if len(info.pipl_effects) == 1
                       else output_stem(source))
        wasm, manifest = build_model(info.sha256, effect_name, fitted)
        text = success_text(source, output, info, manifest, fitted,
                            language) + pipl_report_line(info, language)
        if profile:
            text += '\n' + profile_report(profile, language)
        created = []
        try:
            with output.open('xb') as file:
                created.append(output)
                file.write(wasm)
            with conversion_report.open('x', encoding='utf-8') as file:
                created.append(conversion_report)
                file.write(text)
        except BaseException:
            for path in created:
                path.unlink(missing_ok=True)
            raise
        return conversion_report
    if ae_values and info.family != 'deep_glow':
        raise ValueError('Снимок числовых значений AE поддерживается только для Deep Glow.')
    settings = load_ae_settings(ae_values, info.pipl_effects) if ae_values else None
    output.parent.mkdir(parents=True, exist_ok=True)
    if info.family not in _PORTS:
        # No renamed PE and no unrelated/stub effect: the report is a real
        # outcome of inspecting this binary, with a distinct file extension.
        created = False
        try:
            with report.open('x', encoding='utf-8') as file:
                created = True
                text = unported_report_text(source, info, language)
                if profile:
                    text += '\n' + profile_report(profile, language)
                file.write(text)
        except BaseException:
            if created:
                report.unlink(missing_ok=True)
            raise
        raise UnsupportedAexError(report)

    manifest, wasm, digest = _PORTS[info.family]
    if hashlib.sha256(wasm).hexdigest() != digest or manifest.get('api') != 1:
        raise RuntimeError('Встроенный EffectCraft WASM повреждён; конвертация прервана.')
    applied = None
    if settings:
        applied = select_deep_glow_defaults(settings, manifest)
        wasm, manifest = customized_wasm(wasm, manifest, applied.defaults)
    text = report_text(source, output, info, language)
    if profile:
        text += '\n' + profile_report(profile, language)
    if settings:
        text += '\n' + settings_report(settings, applied, language)
    if info.family == 'deep_glow':
        label = 'SHA-256 of produced WASM' if language == 'en' else 'SHA-256 созданного WASM'
        text += f'\n- {label}: `{hashlib.sha256(wasm).hexdigest()}`\n'
    created = []
    try:
        with output.open('xb') as file:
            created.append(output)
            file.write(wasm)
        with report.open('x', encoding='utf-8') as file:
            created.append(report)
            file.write(text)
        if script is not None:
            with script.open('x', encoding='utf-8') as file:
                created.append(script)
                file.write(BOUNDS_SCRIPT)
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
    return name or 'effect'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Inspect any AE .aex and export independent EffectCraft WASM ports')
    parser.add_argument('input', type=Path, help='AE .aex effect DLL (also .aex.txt)')
    parser.add_argument('output', type=Path, nargs='?', help='New .wasm file (never overwritten)')
    parser.add_argument('--language', choices=('ru', 'en'), default='ru')
    parser.add_argument('--ae-profile', type=Path,
                        help='Optional value-free AE-host metadata JSON; reports only, not a renderer')
    parser.add_argument('--ae-values', type=Path,
                        help='Optional Deep Glow numeric settings snapshot exported from a selected AE effect')
    parser.add_argument('--prepare-reference', type=Path, metavar='DIR',
                        help='Generate two PNG input charts to render in installed AE')
    parser.add_argument('--reference-dir', type=Path, metavar='DIR',
                        help='Fit a validated colour LUT or measured line-glow model from AE PNGs')
    parser.add_argument('--reference-model', choices=('colour', 'line'), default='colour',
                        help='colour: pixel-local LUT (default); line: opaque straight-line glow')
    args = parser.parse_args(argv)
    if args.prepare_reference:
        if args.reference_dir or args.ae_values or args.ae_profile or args.output:
            parser.error('--prepare-reference takes only the input .aex and directory')
        info = inspect_aex(args.input)
        if 'EffectMain' not in info.exports and not info.pipl_effects:
            parser.error('Input is not an identified AE effect DLL')
        training, check = prepare_charts(args.prepare_reference, aex_digest=info.sha256)
        print(f'Charts: {training}\n        {check}\n'
              f'Export AE-rendered PNGs into this folder; see {args.prepare_reference / "HOW_TO_RENDER.txt"}')
        return 0
    output = args.output or args.input.with_name(output_stem(args.input) + '_effectcraft.wasm')
    try:
        report = convert_aex(args.input, output, language=args.language,
                             ae_profile=args.ae_profile, ae_values=args.ae_values,
                             reference_dir=args.reference_dir,
                             reference_model=args.reference_model)
    except UnsupportedAexError as exc:
        if args.language == 'en':
            reason = (('Reference validation rejected the measured line model'
                       if args.reference_model == 'line' else
                       'Reference validation rejected the measured colour model')
                      if args.reference_dir else 'No independent port is available')
            print(f'{reason}; no WASM created. Report: {exc.report}', file=sys.stderr)
        else:
            reason = (('Эталоны не подтвердили процедурный прямой луч'
                       if args.reference_model == 'line' else
                       'Эталоны не подтвердили измеренную цветовую модель')
                      if args.reference_dir else 'Нет независимого порта')
            print(f'{reason}; WASM не создан. Диагностика: {exc.report}', file=sys.stderr)
        return 2
    print(f'Создано: {output}\nОтчёт: {report}')
    if args.reference_dir:
        if args.reference_model == 'line':
            print('Создан экспериментальный процедурный луч: НЕ алгоритм Saber; '
                  'см. ограничения и ошибку проверки в отчёте.')
        else:
            print('Создан экспериментальный измеренный цветовой порт с Mix; настройки AE не перенесены.')
    elif inspect_aex(args.input).family == 'deep_glow':
        print(f'Применение с расширенными границами: {bounds_script_path(output)}')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'Conversion failed: {exc}', file=sys.stderr)
        raise SystemExit(1) from exc
