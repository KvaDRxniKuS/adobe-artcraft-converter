"""Opt-in AE-host numeric snapshot for Deep Glow; never inferred from a .aex.

Only six identically named scalar controls have an explicit mapping. The
original plug-in has other controls (for example Tint Mix and Blend Mode) with
different semantics/option ordering; copying those numbers would mislead users.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .aex_metadata import AEEffectIdentity
from .ae_profile import MAX_PROFILE_BYTES, MAX_PROPERTIES

FORMAT = 'artcraft.ae-effect-values'
# Exact original English UI labels. These are *not* inferred from arbitrary
# .aex files; values only come from a user-selected effect inside AE.
DEEP_GLOW_LABELS = {
    'Radius': 'radius',
    'Exposure': 'exposure',
    'Threshold': 'threshold',
    'Threshold Smooth': 'threshold_smooth',
    'Spread': 'spread',
    'Source Opacity': 'source_opacity',
}


@dataclass(frozen=True)
class ScalarValue:
    name: str
    match_name: str
    groups: tuple[str, ...]
    value: float


@dataclass(frozen=True)
class AESettings:
    effect_name: str
    effect_match_name: str
    properties: tuple[ScalarValue, ...]
    pipl_match: bool | None


@dataclass(frozen=True)
class AppliedSettings:
    defaults: dict[str, float]
    skipped: tuple[str, ...]


def _text(value: object, field: str, limit: int = 256) -> str:
    if not isinstance(value, str) or not 0 < len(value) <= limit or any(
            ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(f'Invalid AE settings {field}')
    return value


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate AE settings field: {key}')
        result[key] = value
    return result


def load_ae_settings(path: Path, identities: tuple[AEEffectIdentity, ...]) -> AESettings:
    """Read a small, explicitly exported scalar-only PEDG snapshot."""
    with Path(path).open('rb') as file:
        raw = file.read(MAX_PROFILE_BYTES + 1)
    if len(raw) > MAX_PROFILE_BYTES:
        raise ValueError('AE settings snapshot is too large (maximum 1 MiB)')
    try:
        data = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('AE settings snapshot must be valid UTF-8 JSON') from exc
    if (not isinstance(data, dict) or data.get('format') != FORMAT
            or type(data.get('version')) is not int or data['version'] != 1):
        raise ValueError('Unknown AE settings snapshot format/version')
    if set(data) != {'format', 'version', 'effect_name', 'effect_match_name', 'properties'}:
        raise ValueError('Unexpected AE settings fields (project paths/media are forbidden)')
    name = _text(data['effect_name'], 'effect_name')
    match = _text(data['effect_match_name'], 'effect_match_name')
    if match != 'PEDG':
        raise ValueError('AE settings snapshot is not from Deep Glow (PEDG)')
    known_matches = {effect.match_name for effect in identities if effect.match_name}
    if known_matches and match not in known_matches:
        raise ValueError('AE settings match name does not match the .aex PiPL')
    items = data['properties']
    if not isinstance(items, list) or not 0 < len(items) <= MAX_PROPERTIES:
        raise ValueError('Invalid AE settings property list')
    props = []
    for i, item in enumerate(items):
        if (not isinstance(item, dict) or set(item) !=
                {'name', 'match_name', 'groups', 'value_type', 'value'}):
            raise ValueError(f'Invalid AE settings property {i} (only scalar values are allowed)')
        if item['value_type'] != 'scalar':
            raise ValueError(f'Invalid AE settings property {i} type')
        groups = item['groups']
        if not isinstance(groups, list) or len(groups) > 16:
            raise ValueError(f'Invalid AE settings property {i} group path')
        value = item['value']
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f'Invalid AE settings property {i} numeric value')
        try:
            number = float(value)
        except (OverflowError, ValueError) as exc:
            raise ValueError(f'Invalid AE settings property {i} numeric value') from exc
        if not math.isfinite(number):
            raise ValueError(f'Invalid AE settings property {i} numeric value')
        props.append(ScalarValue(
            _text(item['name'], 'property.name'),
            _text(item['match_name'], 'property.match_name'),
            tuple(_text(g, 'property.group', 128) for g in groups), number))
    return AESettings(name, match, tuple(props), True if known_matches else None)


def select_deep_glow_defaults(settings: AESettings, manifest: dict) -> AppliedSettings:
    """Copy only unambiguous, in-range scalar labels; report every exception."""
    by_id = {p['id']: p for p in manifest['params']}
    names = Counter(p.name for p in settings.properties)
    defaults: dict[str, float] = {}
    skipped = []
    for prop in settings.properties:
        pid = DEEP_GLOW_LABELS.get(prop.name)
        if pid is None:
            skipped.append(f'{prop.name}: no verified one-to-one port control')
            continue
        if names[prop.name] != 1:
            skipped.append(f'{prop.name}: duplicate label; ambiguous source value')
            continue
        spec = by_id[pid]
        if not spec['min'] <= prop.value <= spec['max']:
            skipped.append(f'{prop.name}: {prop.value} outside the port range '
                           f'{spec["min"]}..{spec["max"]} (not clamped)')
            continue
        defaults[pid] = int(prop.value) if prop.value.is_integer() else prop.value
    return AppliedSettings(defaults, tuple(skipped))


def settings_report(settings: AESettings, applied: AppliedSettings, language: str = 'ru') -> str:
    """State which OBSERVED settings were used and which were not."""
    english = language == 'en'
    lines = (['## AE-host numeric settings snapshot (opt-in)', '',
              f'- Selected effect: {settings.effect_name} (`{settings.effect_match_name}`)',
              f'- Match name compared against .aex PiPL: {"yes" if settings.pipl_match else "unknown"}',
              '- Source: user-supplied JSON intended to come from an AE effect; values cannot be',
              '  authenticated and were **NOT** decoded from its DLL.',
              '- Factory defaults only if the effect was freshly added with unchanged parameters;',
              '  keyframes/expressions or edits may affect the exported numbers.',
              '- Copied numerically by exact control label. Units, algorithms and visual parity are',
              '  unverified. Settings of existing EffectCraft instances are NOT changed.', '']
             if english else
             ['## Числовой снимок настроек из AE (по выбору пользователя)', '',
              f'- Выбранный эффект: {settings.effect_name} (`{settings.effect_match_name}`)',
              '- Match name сверен с PiPL: ' + ('да' if settings.pipl_match else 'неизвестно'),
              '- Источник: предоставленный JSON, предполагается экспорт с экземпляра в AE;',
              '  подлинность значений не проверяется, из DLL они **НЕ** извлечены.',
              '- Заводские значения только если экземпляр был создан заново без изменений;',
              '  ключевые кадры, выражения и правки могут повлиять на числовые значения.',
              '- Перенос по точным названиям: соответствие единиц, алгоритмов и картинки',
              '  НЕ подтверждено. Уже добавленные в EffectCraft эффекты не меняются.', ''])
    lines.append('Applied to new effect defaults:' if english else 'Перенесено в начальные значения новых эффектов:')
    for pid, value in applied.defaults.items():
        lines.append(f'- `{pid}` = {value}')
    if not applied.defaults:
        lines.append('- none (port retains its independent defaults)' if english else
                     '- ничего (остаются собственные значения порта)')
    lines.append('Skipped:' if english else 'Не перенесено:')
    for line in applied.skipped[:40]:
        lines.append('- ' + line)
    if len(applied.skipped) > 40:
        lines.append(f'- ... and {len(applied.skipped) - 40} other controls')
    if not applied.skipped:
        lines.append('- none' if english else '- нет')
    return '\n'.join(lines) + '\n'
