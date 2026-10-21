"""Best-effort raster export of FilmCraft generated Graphic clips.

FilmCraft stores a Graphic canvas on the project item and text/style on the
*clip* as a graphic_text effect. A Premiere media clip cannot reference that
FilmCraft-only object directly, so each occurrence becomes its own transparent
PNG. This does not create an editable Premiere Essential Graphics title.
"""
from __future__ import annotations

import math
import os
import re
from io import BytesIO
from pathlib import Path

MAX_GRAPHIC_PIXELS = 20_000_000  # Two RGBA canvases already require ~160 MB at this limit.


def _value(params: dict, name: str, variant: str, default):
    entry = params.get(name) or {}
    value = entry.get('value') if isinstance(entry, dict) else None
    return value.get(variant, default) if isinstance(value, dict) else default


def _number(value, default: float) -> float:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (ValueError, TypeError):
        return default


def _rgba(value, opacity: float = 100) -> tuple[int, int, int, int]:
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        value = [1, 1, 1, 1]
    rgba = [round(max(0., min(1., _number(channel, 1))) * 255)
            for channel in list(value[:4])]
    if len(rgba) == 3:
        rgba.append(255)
    rgba[3] = round(rgba[3] * max(0., min(100., opacity)) / 100)
    return tuple(rgba)


def _font(family: str, size: int, bold: bool, italic: bool, image_font):
    """Use an installed font without embedding a font or guessing a user path."""
    family = Path(str(family).replace('\\', '/')).name.strip()
    requested = []
    if family:
        requested.extend([family, family + '.ttf', family + '.otf'])
        system_fonts = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
        normal = re.sub(r'[^a-z0-9]', '', family.casefold())
        if normal and system_fonts.is_dir():
            requested.extend(str(p) for p in system_fonts.iterdir()
                             if p.suffix.lower() in ('.ttf', '.otf')
                             and re.sub(r'[^a-z0-9]', '', p.stem.casefold()).startswith(normal))
    windows = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
    fallback = []
    if windows.is_dir():
        fallback.extend(str(windows / name) for name in
                        ('arialbd.ttf' if bold else 'arial.ttf', 'segoeui.ttf'))
    linux = Path('/usr/share/fonts/truetype/dejavu')
    style = ('-BoldOblique' if bold and italic else '-Bold' if bold else
             '-Oblique' if italic else '')
    fallback.append(str(linux / f'DejaVuSans{style}.ttf'))
    for candidate, replaced in ([(name, False) for name in requested] +
                                [(name, True) for name in fallback]):
        try:
            return image_font.truetype(candidate, size=size), replaced
        except (OSError, ValueError):
            continue
    # load_default(size=...) has a scalable font in Pillow 10+, but on some
    # systems it has limited Unicode coverage. The caller will report fallback.
    try:
        return image_font.load_default(size=size), True
    except (OSError, ValueError) as exc:
        raise ValueError('Нет доступного шрифта для экспорта Graphic в PNG.') from exc


def render_graphic(graphic: dict, effects: list, fallback_width: int,
                   fallback_height: int) -> tuple[bytes, list[str], bool]:
    """Return transparent PNG bytes, diagnostic phrases and whether text was drawn."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise RuntimeError('Для переноса FilmCraft Graphic нужен Pillow. Выполните: '
                           'py -3 -m pip install -r config/requirements.txt') from exc
    width = max(1, int(graphic.get('width') or fallback_width))
    height = max(1, int(graphic.get('height') or fallback_height))
    if width * height > MAX_GRAPHIC_PIXELS:
        raise ValueError(f'Graphic {width}×{height} слишком велик для безопасного экспорта PNG.')
    image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    warnings = []
    drawn = False
    for effect in effects or []:
        if not isinstance(effect, dict) or effect.get('effect') != 'graphic_text':
            continue
        if effect.get('enabled') is False:
            warnings.append('Отключённый слой graphic_text не нарисован.')
            continue
        params = effect.get('params') or {}
        if not isinstance(params, dict):
            warnings.append('Параметры graphic_text некорректны; слой не нарисован.')
            continue
        text = _value(params, 'text', 'Text', '')
        if not isinstance(text, str) or not text:
            warnings.append('Пустой graphic_text не нарисован.')
            continue
        if len(text) > 5000:
            raise ValueError('Graphic text слишком длинный для безопасной растеризации PNG.')
        size = max(1, min(2048, round(_number(_value(params, 'size', 'Float', 60), 60))))
        family = _value(params, 'font', 'Text', '')
        style = _value(params, 'font_style', 'Text', '')
        bold = bool(_value(params, 'faux_bold', 'Bool', False)) or 'bold' in str(style).lower()
        italic = bool(_value(params, 'faux_italic', 'Bool', False)) or 'italic' in str(style).lower()
        font, fallback = _font(family, size, bold, italic, ImageFont)
        if fallback:
            warnings.append('Исходный шрифт Graphic недоступен; использован запасной.')
        opacity = _number(_value(params, 'opacity', 'Float', 100), 100)
        color = _rgba(_value(params, 'fill_color', 'Color', [1, 1, 1, 1]), opacity)
        if not _value(params, 'fill', 'Bool', True):
            color = color[:3] + (0,)
        stroke = bool(_value(params, 'stroke', 'Bool', False))
        stroke_width = min(200, max(0, round(_number(
            _value(params, 'stroke_width', 'Float', 0), 0)))) if stroke else 0
        stroke_color = _rgba(_value(params, 'stroke_color', 'Color', [0, 0, 0, 1]), opacity)
        position = _value(params, 'position', 'Vec2', {})
        if not isinstance(position, dict):
            position = {}
        x = _number(position.get('x'), width / 2)
        y = _number(position.get('y'), height / 2)
        alignment = _value(params, 'align', 'Choice', 0)
        spacing = max(1, size * 1.2 + _number(_value(params, 'leading', 'Float', 0), 0))
        layer = Image.new('RGBA', image.size, (0, 0, 0, 0))
        pen = ImageDraw.Draw(layer)
        for line_no, line in enumerate(text.split('\n')):
            try:
                bounds = pen.textbbox((0, 0), line, font=font, stroke_width=stroke_width)
                line_width = bounds[2] - bounds[0]
                offset = line_width / 2 if alignment == 1 else line_width if alignment == 2 else 0
                pen.text((x - offset, y + line_no * spacing), line, font=font,
                         anchor='lt', fill=color, stroke_width=stroke_width,
                         stroke_fill=stroke_color)
            except UnicodeEncodeError as exc:
                raise ValueError('Доступный шрифт не поддерживает символы Graphic; '
                                 'текст не сохранён.') from exc
        angle = _number(_value(params, 'rotation', 'Float', 0), 0)
        if angle:
            layer = layer.rotate(-angle, resample=Image.Resampling.BICUBIC,
                                 center=(x, y), expand=False)
        image = Image.alpha_composite(image, layer)
        drawn = True
        if (_value(params, 'shadow', 'Bool', False) or
                _value(params, 'background', 'Bool', False) or
                _value(params, 'stroke2', 'Bool', False) or
                _value(params, 'fill_kind', 'Choice', 0) != 0 or
                _value(params, 'vertical', 'Bool', False)):
            warnings.append('Фон/тень/градиент/второй контур/вертикальный набор '
                            'Graphic перенесены не полностью.')
        if any(isinstance(entry, dict) and
               (entry.get('keyframes') or entry.get('animation'))
               for entry in params.values()):
            warnings.append('Анимация параметров Graphic не перенесена в статичный PNG.')
        if (italic or _number(_value(params, 'scale', 'Float', 100), 100) != 100 or
                _number(_value(params, 'tracking', 'Float', 0), 0) != 0):
            warnings.append('Наклон/масштаб/межбуквенный интервал Graphic '
                            'могут отличаться от FilmCraft.')
    if drawn and image.getchannel('A').getbbox() is None:
        warnings.append('Текст Graphic оказался полностью прозрачным или вне холста.')
        drawn = False
    buffer = BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue(), warnings, drawn
