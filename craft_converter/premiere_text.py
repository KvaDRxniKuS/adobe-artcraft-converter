"""Experimental native Premiere Type-tool Source Text encoding (static text).

The 26.x FlatBuffer slot layout and synthetic-media graph are derived from the
MIT-licensed Tesseract-Converter text writer/fixtures. Full attribution and the
MIT license are included in premiere_text_seed.py. This is a limited subset:
animated, multi-layer, shadow/background/gradient text requires a raster fallback.
Adobe has not published a public schema for this binary field.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass

MAGIC = 0x11223344


class NativeTextUnsupported(ValueError):
    """A graphic_text layer needs the existing PNG fallback."""


@dataclass(frozen=True)
class NativeText:
    payload: bytes
    parameters: dict[int, str]
    warnings: list[str]


def _value(params: dict, name: str, variant: str, default):
    entry = params.get(name) or {}
    value = entry.get('value') if isinstance(entry, dict) else None
    return value.get(variant, default) if isinstance(value, dict) else default


def _number(value, default: float, *, low=-1e6, high=1e6) -> float:
    try:
        x = float(value)
    except (ValueError, TypeError):
        x = default
    if not math.isfinite(x) or not low <= x <= high:
        raise NativeTextUnsupported('Недопустимое числовое значение параметра Graphic.')
    return x


def _rgb(params: dict, name: str, default: list[float]) -> tuple[int, int, int]:
    raw = _value(params, name, 'Color', default)
    if not isinstance(raw, (list, tuple)) or len(raw) < 3:
        raise NativeTextUnsupported('Некорректный цвет текста Graphic.')
    if len(raw) >= 4 and _number(raw[3], 1) < 1:
        raise NativeTextUnsupported('Прозрачность заливки или обводки требует PNG.')
    return tuple(round(max(0.0, min(1.0, _number(x, 1))) * 255) for x in raw[:3])


def _param_tables(text: str, font: str, size: float, fill: tuple[int, int, int] | None,
                  stroke: tuple[tuple[int, int, int], float] | None,
                  tracking: float, caps: bool, leading: float,
                  justification: int, box: tuple[float, float] | None) -> bytes:
    try:
        from flatbuffers import Builder
    except ImportError as exc:
        raise NativeTextUnsupported('Для нативного текста нужен flatbuffers; установите config/requirements.txt.') from exc
    b = Builder(512)

    def color_table(color):
        b.StartObject(3)
        b.ForceDefaults(True)
        for slot, component in enumerate(color):
            b.PrependUint8Slot(slot, component, 0)  # Preserve explicit zero channels.
        result = b.EndObject()
        b.ForceDefaults(False)
        return result

    def empty_table():
        b.StartObject(0)
        return b.EndObject()

    def vector(offsets):
        b.StartVector(4, len(offsets), 4)
        for off in reversed(offsets):
            b.PrependUOffsetTRelative(off)
        return b.EndVector()

    fill_table = color_table(fill) if fill is not None and fill != (255, 255, 255) else None
    stroke_table = color_table(stroke[0]) if stroke else None
    blank_21, blank_23 = empty_table(), empty_table()
    b.StartObject(25)
    b.PrependFloat32Slot(1, size, 100.0)
    if fill is None:
        b.PrependUint8Slot(3, 0, 1)
    elif fill_table is not None:
        b.PrependUOffsetTRelativeSlot(2, fill_table, 0)
    if stroke and stroke_table is not None:
        b.PrependUOffsetTRelativeSlot(4, stroke_table, 0)
        b.PrependUint8Slot(5, 1, 0)
        b.PrependFloat32Slot(6, stroke[1], -1.0)  # Zero-width strokes must also be stored.
    else:
        b.PrependFloat32Slot(6, 4.0, 0.0)
    b.PrependFloat32Slot(8, tracking, 0.0)
    if caps:
        b.PrependUint32Slot(12, 2, 0)
    b.PrependUOffsetTRelativeSlot(21, blank_21, 0)
    b.PrependUOffsetTRelativeSlot(23, blank_23, 0)
    b.PrependUint32Slot(24, 2, 0)
    style = b.EndObject()

    text_str = b.CreateString(text.replace('\r\n', '\n').replace('\r', '\n')
                              .replace('\n', '\r'))
    b.StartObject(2)
    b.PrependUOffsetTRelativeSlot(0, text_str, 0)
    b.PrependUOffsetTRelativeSlot(1, style, 0)
    run = b.EndObject()
    runs = vector([run])
    font_str = b.CreateString(font)
    fonts = vector([font_str])
    empty_doc = empty_table()

    b.StartObject(45)
    b.PrependUOffsetTRelativeSlot(0, runs, 0)
    b.PrependUOffsetTRelativeSlot(1, fonts, 0)
    if box:
        b.PrependFloat32Slot(2, box[0], 0.0)
        b.PrependFloat32Slot(3, box[1], 0.0)
    b.PrependUint32Slot(4, justification, 0)
    b.PrependFloat32Slot(6, leading, 0.0)
    b.PrependUint8Slot(26, 1, 0)
    b.PrependUOffsetTRelativeSlot(40, empty_doc, 0)
    b.PrependUint8Slot(43, 0, 1)
    b.PrependUint8Slot(44, 1, 0)
    document = b.EndObject()
    b.StartObject(1)
    b.PrependUOffsetTRelativeSlot(0, document, 0)
    root = b.EndObject()
    b.Finish(root)
    buffer = bytes(b.Output())
    return struct.pack('<QI', len(buffer), MAGIC) + buffer


def create_native_text(effect: dict, graphic: dict, width: int, height: int) -> NativeText:
    """Encode one static FC graphic_text effect as editable native Source Text."""
    if effect.get('enabled') is False:
        raise NativeTextUnsupported('Слой текста выключен.')
    params = effect.get('params') or {}
    if not isinstance(params, dict):
        raise NativeTextUnsupported('Параметры текста Graphic не являются объектом.')
    if any(isinstance(entry, dict) and (entry.get('keyframes') or entry.get('animation'))
           for entry in params.values()):
        raise NativeTextUnsupported('Анимация текста не поддержана в нативном режиме.')
    unsupported = ('shadow', 'background', 'stroke2', 'vertical', 'underline')
    if any(_value(params, field, 'Bool', False) for field in unsupported):
        raise NativeTextUnsupported('Тени/фон/дополнительные стили требуют PNG.')
    if _value(params, 'fill_kind', 'Choice', 0) != 0:
        raise NativeTextUnsupported('Градиентный текст пока требует PNG.')
    if _number(_value(params, 'baseline_shift', 'Float', 0), 0) != 0:
        raise NativeTextUnsupported('Смещение базовой линии пока требует PNG.')
    if not _value(params, 'kerning', 'Bool', True) or not _value(params, 'ligatures', 'Bool', True):
        raise NativeTextUnsupported('Особые настройки кернинга/лигатур пока требуют PNG.')
    text = _value(params, 'text', 'Text', '')
    if not isinstance(text, str) or not text or len(text) > 5000:
        raise NativeTextUnsupported('Пустой или слишком длинный текст требует PNG.')
    font = _value(params, 'font', 'Text', 'ArialMT')
    if not isinstance(font, str) or not font or len(font) > 255:
        raise NativeTextUnsupported('Некорректное название шрифта.')
    size = _number(_value(params, 'size', 'Float', 100), 100, low=1, high=2048)
    fill = _rgb(params, 'fill_color', [1, 1, 1, 1]) if _value(params, 'fill', 'Bool', True) else None
    stroke = None
    if _value(params, 'stroke', 'Bool', False):
        if _value(params, 'stroke_type', 'Choice', 0) != 0:
            raise NativeTextUnsupported('Тип обводки текста пока требует PNG.')
        stroke = (_rgb(params, 'stroke_color', [0, 0, 0, 1]),
                  _number(_value(params, 'stroke_width', 'Float', 4), 4, low=0, high=200))
    tracking = _number(_value(params, 'tracking', 'Float', 0), 0, low=-500, high=500)
    leading = _number(_value(params, 'leading', 'Float', 0), 0, low=-2048, high=2048)
    caps_choice = _value(params, 'caps', 'Choice', 0)
    align = _value(params, 'align', 'Choice', 0)
    if caps_choice not in (0, 2) or align not in (0, 1, 2, 3):
        raise NativeTextUnsupported('Неподдерживаемый регистр или выравнивание требует PNG.')
    caps = caps_choice == 2
    justification = {0: 0, 1: 2, 2: 1, 3: 3}[align]
    box_width = _number(_value(params, 'box_width', 'Float', 0), 0, low=0, high=100000)
    box_height = _number(_value(params, 'box_height', 'Float', 0), 0, low=0, high=100000)
    if bool(box_width) != bool(box_height):
        raise NativeTextUnsupported('Неполная текстовая рамка требует PNG.')
    box = (box_width, box_height) if box_width else None
    payload = _param_tables(text, font, size, fill, stroke, tracking, caps, leading,
                            justification, box)
    # Premiere stores point positions as fractions of the sequence frame.
    gwidth = max(1, _number(graphic.get('width'), width, low=1))
    gheight = max(1, _number(graphic.get('height'), height, low=1))

    def point(name):
        default = {'x': gwidth / 2, 'y': gheight / 2} if name == 'position' else {'x': 0, 'y': 0}
        raw = _value(params, name, 'Vec2', default)
        if not isinstance(raw, dict):
            raise NativeTextUnsupported('Некорректные координаты текста Graphic.')
        x = _number(raw.get('x'), 0) / gwidth
        y = _number(raw.get('y'), 0) / gheight
        return f'{x:.9g}:{y:.9g}'

    values = {
        3: point('position'), 9: point('anchor'),
        4: str(_number(_value(params, 'scale', 'Float', 100), 100, low=0.01, high=10000)),
        5: str(_number(_value(params, 'scale_width', 'Float', 100), 100, low=0.01, high=10000)),
        6: str(bool(_value(params, 'uniform_scale', 'Bool', True))).lower(),
        7: str(_number(_value(params, 'rotation', 'Float', 0), 0)),
        8: str(_number(_value(params, 'opacity', 'Float', 100), 100, low=0, high=100)),
    }
    warnings = ['Нативный текст Premiere построен экспериментально; откройте и проверьте титр в Premiere Pro.']
    if _value(params, 'font_style', 'Text', '') not in ('', 'Regular') or _value(params, 'faux_bold', 'Bool', False):
        warnings.append('Начертание шрифта может отличаться; в Premiere нужен установленный исходный шрифт.')
    if _value(params, 'faux_italic', 'Bool', False) or _value(params, 'stroke2', 'Bool', False):
        warnings.append('Дополнительные стили текста перенесены не полностью.')
    return NativeText(payload, values, warnings)
