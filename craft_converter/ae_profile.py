"""Validate an optional parameter inventory exported from After Effects.

AE-host metadata can show property groups, bounds and animation support. It
cannot disclose a plug-in's render algorithm or force EffectCraft to expose UI
widgets its WASM API does not implement. No property *values* are imported.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from .aex_metadata import AEEffectIdentity

MAX_PROFILE_BYTES = 1024 * 1024
MAX_PROPERTIES = 512
FORMAT = 'artcraft.ae-parameter-profile'


@dataclass(frozen=True)
class AEParameter:
    name: str
    match_name: str
    groups: tuple[str, ...]
    value_type: str
    has_min: bool | None
    has_max: bool | None
    min_value: float | None
    max_value: float | None
    can_vary_over_time: bool | None
    can_set_expression: bool | None
    ui_control: str


@dataclass(frozen=True)
class AEProfile:
    effect_name: str
    effect_match_name: str
    properties: tuple[AEParameter, ...]
    pipl_match: bool | None


def _text(value: object, *, field: str, max_length: int = 256) -> str:
    if not isinstance(value, str) or not 0 < len(value) <= max_length:
        raise ValueError(f'Invalid AE profile {field}')
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(f'Invalid AE profile {field}')
    return value


def _flag(value: object, field: str) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    raise ValueError(f'Invalid AE profile {field}: expected boolean or null')


def _bound(value: object, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'Invalid AE profile {field}: expected a number or null')
    if not math.isfinite(value):
        raise ValueError(f'Invalid AE profile {field}: non-finite number')
    return float(value)


def load_ae_profile(path: Path, identities: tuple[AEEffectIdentity, ...]) -> AEProfile:
    """Load bounded, value-free AE metadata and check it against the DLL PiPL."""
    path = Path(path)
    with path.open('rb') as file:
        raw = file.read(MAX_PROFILE_BYTES + 1)
    if len(raw) > MAX_PROFILE_BYTES:
        raise ValueError('AE profile is too large (maximum 1 MiB)')
    try:
        data = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('AE profile must be valid UTF-8 JSON') from exc
    if not isinstance(data, dict) or data.get('format') != FORMAT or data.get('version') != 1:
        raise ValueError('Unknown AE profile format/version')
    if set(data) != {'format', 'version', 'effect_name', 'effect_match_name', 'properties'}:
        raise ValueError('Unexpected AE profile fields (values and project paths are forbidden)')
    effect_name = _text(data['effect_name'], field='effect_name')
    match_name = _text(data['effect_match_name'], field='effect_match_name')
    items = data['properties']
    if not isinstance(items, list) or len(items) > MAX_PROPERTIES:
        raise ValueError('Invalid AE profile property list')
    properties = []
    required = {'name', 'match_name', 'groups', 'value_type', 'has_min', 'has_max',
                'min_value', 'max_value', 'can_vary_over_time', 'can_set_expression',
                'ui_control'}
    for index, item in enumerate(items):
        if not isinstance(item, dict) or set(item) != required:
            raise ValueError(f'Invalid AE profile property {index} (values are forbidden)')
        groups = item['groups']
        if not isinstance(groups, list) or len(groups) > 16:
            raise ValueError(f'Invalid AE profile property {index} group path')
        group_names = tuple(_text(g, field='group', max_length=128) for g in groups)
        has_min = _flag(item['has_min'], 'has_min')
        has_max = _flag(item['has_max'], 'has_max')
        min_value = _bound(item['min_value'], 'min_value')
        max_value = _bound(item['max_value'], 'max_value')
        if ((has_min is not True and min_value is not None)
                or (has_max is not True and max_value is not None)
                or (min_value is not None and max_value is not None and min_value > max_value)):
            raise ValueError(f'Conflicting AE profile property {index} bounds')
        control = _text(item['ui_control'], field='ui_control', max_length=32)
        if control != 'unknown':
            # AE's scripting property model does not reliably distinguish a
            # slider from a number field or expose proprietary curve widgets.
            raise ValueError('AE UI control must be marked unknown in this profile')
        properties.append(AEParameter(
            _text(item['name'], field='property.name'),
            _text(item['match_name'], field='property.match_name'), group_names,
            _text(item['value_type'], field='property.value_type', max_length=64),
            has_min, has_max, min_value, max_value,
            _flag(item['can_vary_over_time'], 'can_vary_over_time'),
            _flag(item['can_set_expression'], 'can_set_expression'), control,
        ))
    known_matches = {effect.match_name for effect in identities if effect.match_name}
    if known_matches and match_name not in known_matches:
        raise ValueError('AE profile match name does not match the .aex PiPL')
    # A missing PiPL (or one lacking a match name) is not a failed comparison.
    return AEProfile(effect_name, match_name, tuple(properties),
                     True if known_matches else None)


def profile_report(profile: AEProfile, language: str = 'ru') -> str:
    """Human-readable, provenance-labelled facts; no guessed slider or kernel."""
    english = language == 'en'
    yes = ('yes', 'no', 'unknown') if english else ('да', 'нет', 'неизвестно')

    def flag(value: bool | None) -> str:
        return yes[2 if value is None else (0 if value else 1)]

    def range_part(has_bound: bool | None, number: float | None) -> str:
        if has_bound is False:
            return 'none' if english else 'нет'
        if has_bound is None:
            return yes[2]
        return str(number) if number is not None else ('present (value unavailable)' if english
                                                      else 'есть (значение недоступно)')

    if english:
        lines = [
            '## AE-host parameter inventory', '',
            f'- Effect: {profile.effect_name} (`{profile.effect_match_name}`)',
            f'- Match name cross-checked against the DLL PiPL: {flag(profile.pipl_match)}',
            '- Provenance: separate AE script export, **not** metadata decoded from the DLL.',
            '- No project values or media paths are present. Widget shape (slider vs numeric',
            '  field / curve editor) and the render algorithm are **not** exposed by this API.', '',
        ]
    else:
        lines = [
            '## Параметры по инвентаризации из AE', '',
            f'- Эффект: {profile.effect_name} (`{profile.effect_match_name}`)',
            f'- Match name сверен с PiPL файла: {flag(profile.pipl_match)}',
            '- Источник: отдельный экспорт скриптом из AE, **не** извлечение схемы из DLL.',
            '- Значения проекта и пути медиа отсутствуют. Вид виджета (ползунок, числовое',
            '  поле, редактор кривой) и алгоритм рендера этим API **не** раскрываются.', '',
        ]
    for p in profile.properties:
        name = ' › '.join((*p.groups, p.name))
        if english:
            lines.extend([
                f'- **{name}** (`{p.match_name}`, {p.value_type}): '
                f'min {range_part(p.has_min, p.min_value)}; '
                f'max {range_part(p.has_max, p.max_value)}; '
                f'keyframes {flag(p.can_vary_over_time)}; '
                f'expressions {flag(p.can_set_expression)}; UI widget unknown.',
            ])
        else:
            lines.extend([
                f'- **{name}** (`{p.match_name}`, {p.value_type}): '
                f'минимум {range_part(p.has_min, p.min_value)}; '
                f'максимум {range_part(p.has_max, p.max_value)}; '
                f'ключевые кадры {flag(p.can_vary_over_time)}; '
                f'выражения {flag(p.can_set_expression)}; вид элемента UI неизвестен.',
            ])
    if not profile.properties:
        lines.append('No properties reported.' if english else 'Свойств не обнаружено.')
    lines.append('')
    return '\n'.join(lines) + '\n'
