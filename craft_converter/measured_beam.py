"""Fit ONE reusable procedural straight-line glow kernel from AE reference PNGs.

No image, user .aex/.aep or per-plug-in source is embedded in this module. The
only fitted data in a successful WASM are 15 Gaussian amplitudes and a few
manifest defaults. Curves, masks, text, flicker and arbitrary generators are
out of scope; measured failure returns a report and no fake effect.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

from .beam_layout import SIGMAS, patch_wasm, weight_bytes
from .effectcraft_measured_beam import MANIFEST as TEMPLATE_MANIFEST, WASM, WASM_SHA256
from .measured_port import (CHECK_AFTER, CHECK_INPUT, MAX_PNG_BYTES, TRAIN_AFTER,
                            TRAIN_INPUT, ReferenceError, _references)

MAX_MEAN_ERROR = 6.0
MAX_P95_ERROR = 18
BRIGHT_THRESHOLD = 235  # Detect a narrow, neutral-white core, not arbitrary masks.


@dataclass(frozen=True)
class Geometry:
    start: tuple[float, float]  # Fractions of layer width/height, in pixel-centre coords.
    end: tuple[float, float]
    radius: float                # Core radius in full-resolution layer pixels.
    colour: tuple[int, int, int]


@dataclass(frozen=True)
class BeamFit:
    geometry: Geometry | None
    weights: tuple[tuple[float, ...], ...] | None  # RGB-major, 5 scales each.
    train_mae: float | None
    check_mae: float | None
    check_p95: int | None
    observed_change: float | None
    hashes: tuple[str, ...]
    reason: str | None

    @property
    def accepted(self) -> bool:
        return self.reason is None


def _geometry(image) -> Geometry:
    width, height = image.size
    pixels = image.load()
    locations = []
    colours = []
    for y in range(height):
        for x in range(width):
            colour = pixels[x, y]
            if min(colour[:3]) >= BRIGHT_THRESHOLD and colour[3] >= 253:
                locations.append((x + .5, y + .5))
                colours.append(colour[:3])
                if len(locations) > width * height * .08:
                    raise ReferenceError('Bright area is not a narrow line core.')
    n = len(locations)
    if n < 24 or n > width * height * .08:
        raise ReferenceError('No narrow bright line core was found; masks, text, glows without '
                             'a straight white core and arbitrary generators need another model.')
    mx = sum(x for x, _ in locations) / n
    my = sum(y for _, y in locations) / n
    xx = sum((x - mx) ** 2 for x, _ in locations) / n
    yy = sum((y - my) ** 2 for _, y in locations) / n
    xy = sum((x - mx) * (y - my) for x, y in locations) / n
    angle = .5 * math.atan2(2 * xy, xx - yy)
    ux, uy = math.cos(angle), math.sin(angle)
    if uy < 0 or (abs(uy) < 1e-8 and ux < 0):
        ux, uy = -ux, -uy
    projections = [(x - mx) * ux + (y - my) * uy for x, y in locations]
    along_min, along_max = min(projections), max(projections)
    radius = round(max(abs((x - mx) * -uy + (y - my) * ux)
                       for x, y in locations) + .5, 2)
    length = along_max - along_min
    if not (.25 * min(width, height) <= length <= 2 * max(width, height)
            and .5 <= radius <= 16 and length / (2 * radius) >= 8):
        raise ReferenceError('Bright pixels do not form one thin, straight line.')
    start = ((mx + ux * along_min) / width, (my + uy * along_min) / height)
    end = ((mx + ux * along_max) / width, (my + uy * along_max) / height)
    if any(not -.1 <= value <= 1.1 for value in start + end):
        raise ReferenceError('The measured line extends outside the reference layer.')
    core_rgb = tuple(sorted(col[c] for col in colours)[n // 2] for c in range(3))
    return Geometry(start, end, radius, core_rgb)


def _features(width: int, height: int, x: int, y: int, geometry: Geometry):
    sx, sy = geometry.start[0] * width, geometry.start[1] * height
    ex, ey = geometry.end[0] * width, geometry.end[1] * height
    dx, dy = ex - sx, ey - sy
    length = math.hypot(dx, dy)
    ox, oy = x + .5 - sx, y + .5 - sy
    along = (ox * dx + oy * dy) / length
    distance = abs((ox * dy - oy * dx) / length)
    return (along, distance, length, tuple(
        math.exp(-.5 * (distance / s) ** 2) * .5 * (
            math.erf(along / (math.sqrt(2) * s)) -
            math.erf((along - length) / (math.sqrt(2) * s))) for s in SIGMAS))


def _fit_weights(after, geometry: Geometry) -> tuple[tuple[float, ...], ...]:
    width, height = after.size
    n = len(SIGMAS)
    matrices = [[[0.0] * n for _ in range(n)] for _ in range(3)]
    targets = [[0.0] * n for _ in range(3)]
    pixels = after.load()
    stride = max(1, int(math.sqrt(width * height / 28000)))
    for y in range(0, height, stride):
        for x in range(0, width, stride):
            actual = pixels[x, y]
            if min(actual[:3]) >= BRIGHT_THRESHOLD:  # Solid core, not emitted glow.
                continue
            features = _features(width, height, x, y, geometry)[3]
            for c in range(3):
                if actual[c] >= 254:  # Clipped colour gives only a lower bound.
                    continue
                for j in range(n):
                    targets[c][j] += features[j] * actual[c]
                    for k in range(n):
                        matrices[c][j][k] += features[j] * features[k]
    rows = []
    for c in range(3):
        values = [0.0] * n
        for _ in range(700):
            for j in range(n):
                diagonal = matrices[c][j][j]
                if diagonal < 1e-8:
                    continue
                other = sum(matrices[c][j][k] * values[k] for k in range(n) if k != j)
                values[j] = max(0.0, (targets[c][j] - other) / diagonal)
        rows.append(tuple(values))
    if any(not math.isfinite(v) or v > 512 for row in rows for v in row):
        raise ReferenceError('Beam coefficients are not finite or exceed the safe range.')
    return tuple(rows)


def render_pixel(width: int, height: int, x: int, y: int,
                 geometry: Geometry, weights) -> tuple[int, int, int]:
    """Python mirror of the WASM procedural renderer, used for validation."""
    along, distance, length, features = _features(width, height, x, y, geometry)
    core = max(0.0, min(1.0, geometry.radius - distance + .5)) * (
        max(0.0, min(1.0, along + 1.0)) *
        max(0.0, min(1.0, length - along + 1.0)))
    return tuple(round(max(0.0, min(255.0,
                   sum(weights[c][j] * features[j] for j in range(len(SIGMAS))) *
                   (1 - core) + geometry.colour[c] * core))) for c in range(3))


def _metrics(before, after, geometry: Geometry, weights, step: int):
    width, height = after.size
    original, result = before.load(), after.load()
    histogram = [0] * 256
    error = change = count = 0
    for y in range(0, height, step):
        for x in range(0, width, step):
            actual = result[x, y]
            predicted = render_pixel(width, height, x, y, geometry, weights)
            old = original[x, y]
            for c in range(3):
                distance = abs(predicted[c] - actual[c])
                histogram[distance] += 1
                error += distance
                change += abs(old[c] - actual[c])
                count += 1
    running = 0
    for p95, frequency in enumerate(histogram):
        running += frequency
        if running >= math.ceil(count * .95):
            break
    return error / count, p95, change / count


def fit(folder: Path, aex_digest: str) -> BeamFit:
    """Fit only the training chart; validate on an unseen, DIFFERENT-SIZED AE frame."""
    folder = Path(folder)
    train_input, train_ae, check_input, check_ae = _references(folder, aex_digest)
    hashes = []
    for name in (TRAIN_INPUT, TRAIN_AFTER, CHECK_INPUT, CHECK_AFTER):
        with (folder / name).open('rb') as stream:
            data = stream.read(MAX_PNG_BYTES + 1)
        if len(data) > MAX_PNG_BYTES:
            raise ReferenceError(f'Reference PNG too large: {name}')
        hashes.append(hashlib.sha256(data).hexdigest())
    if train_ae.getchannel('A').getextrema()[0] < 253 or check_ae.getchannel('A').getextrema()[0] < 253:
        return BeamFit(None, None, None, None, None, None, tuple(hashes),
                       'Transparent output is not supported: only opaque full-frame examples were validated.')
    try:
        geometry = _geometry(train_ae)
        other_geometry = _geometry(check_ae)
    except ReferenceError as exc:
        return BeamFit(None, None, None, None, None, None, tuple(hashes), str(exc))
    delta = max(abs(a - b) for a, b in zip(geometry.start + geometry.end,
                                           other_geometry.start + other_geometry.end))
    if delta > .03 or abs(geometry.radius - other_geometry.radius) > 2.0:
        return BeamFit(geometry, None, None, None, None, None, tuple(hashes),
                       'The core geometry/width changed between AE renders; use identical '
                       'fixed settings, mask and time in both charts.')
    weights = _fit_weights(train_ae, geometry)
    train_mae, _, _ = _metrics(train_input, train_ae, geometry, weights, 4)
    check_mae, p95, changed = _metrics(check_input, check_ae, geometry, weights, 1)
    reason = None
    if changed < 1.5:
        reason = 'No measurable AE effect on the independent chart.'
    elif train_mae > MAX_MEAN_ERROR or check_mae > MAX_MEAN_ERROR or p95 > MAX_P95_ERROR:
        reason = ('This output is not well predicted by one straight line and five '
                  'Gaussian glow scales. Masks, text, complex geometry, backgrounds '
                  'and animation need another model.')
    return BeamFit(geometry, weights, train_mae, check_mae, p95, changed,
                   tuple(hashes), reason)


def build_port(aex_digest: str, name: str, fitted: BeamFit) -> tuple[bytes, dict]:
    if not fitted.accepted or not fitted.geometry or not fitted.weights:
        raise ReferenceError(fitted.reason or 'Unvalidated beam model')
    if hashlib.sha256(WASM).hexdigest() != WASM_SHA256:
        raise RuntimeError('Embedded measured beam renderer is corrupt')
    manifest = json.loads(json.dumps(TEMPLATE_MANIFEST))
    # Different renders/presets have distinct IDs; no full frame is embedded.
    preset_digest = hashlib.sha256((fitted.hashes[1] + fitted.hashes[3]).encode('ascii')).hexdigest()
    manifest['id'] = 'org.artcraft_converter.measured_line.' + hashlib.sha256(
        (aex_digest + preset_digest).encode('ascii')).hexdigest()[:24]
    safe_name = ''.join(c if c.isprintable() else ' ' for c in name).strip()
    manifest['name'] = (safe_name[:42] or 'AE line generator') + ' (measured line)'
    manifest['description'] = ('Independent straight-line Gaussian glow fitted from TWO AE renders '
                               'at one fixed preset. NOT the .aex algorithm; no masks, text, '
                               'animation or transparent outputs. Check MAE '
                               f'{fitted.check_mae:.2f}/255, p95 {fitted.check_p95}/255.')
    defaults = {item['id']: item for item in manifest['params']}
    defaults['start']['default'] = list(fitted.geometry.start)
    defaults['end']['default'] = list(fitted.geometry.end)
    defaults['core_radius']['default'] = fitted.geometry.radius
    defaults['core_color']['default'] = [c / 255 for c in fitted.geometry.colour] + [1]
    return patch_wasm(WASM, TEMPLATE_MANIFEST, manifest, weight_bytes(fitted.weights)), manifest


def report_text(source: Path, output: Path, info, manifest: dict, fitted: BeamFit,
                language: str = 'ru') -> str:
    hashes = '\n'.join(f'- `{name}` SHA-256: `{digest}`' for name, digest in zip(
        (TRAIN_INPUT, TRAIN_AFTER, CHECK_INPUT, CHECK_AFTER), fitted.hashes))
    if language == 'en':
        return (f'# Measured procedural line → EffectCraft (EXPERIMENTAL)\n\n'
                f'- AEX: `{source.name}` SHA-256 `{info.sha256}`; WASM: `{output.name}`\n'
                f'- Fit error (training): {fitted.train_mae:.2f}/255; different-size check: '
                f'MAE {fitted.check_mae:.2f}/255, p95 {fitted.check_p95}/255\n'
                f'- Core: {fitted.geometry.start} → {fitted.geometry.end}; '
                f'radius {fitted.geometry.radius:.1f} px; effect ID `{manifest["id"]}`\n'
                f'{hashes}\n\n'
                'A general, independently coded STRAIGHT-LINE Gaussian glow renders from 15 '
                'fitted numbers and adjustable points, core, glow size, brightness and Mix. '
                'This is NOT Saber or a translation of its DLL. The AE project was not parsed, '
                'no frame was embedded; output REPLACES the layer with an opaque black-based '
                'beam. Use a composition-sized opaque solid to avoid footage-bound clipping. '
                'Only two opaque frames of different sizes were available, so input '
                'independence, alpha/composite behaviour, animation and other presets are '
                'NOT established. The second frame measured pixel error, but this beam family '
                'was developed with these examples in view: obtain another background or '
                'changed path/time for a genuinely new validation. No masks, text, flicker, '
                'distortion, AE controls or HDR; at most 9 million pixels per frame. '
                'Check actual playback in EffectCraft desktop.\n')
    return (f'# Измеренный процедурный луч → EffectCraft (ЭКСПЕРИМЕНТ)\n\n'
            f'- AEX: `{source.name}` SHA-256 `{info.sha256}`; WASM: `{output.name}`\n'
            f'- Ошибка на обучении: {fitted.train_mae:.2f}/255; на другом размере: '
            f'средняя {fitted.check_mae:.2f}/255, p95 {fitted.check_p95}/255\n'
            f'- Сердцевина: {fitted.geometry.start} → {fitted.geometry.end}; '
            f'радиус {fitted.geometry.radius:.1f} пикс.; ID `{manifest["id"]}`\n'
            f'{hashes}\n\n'
            'Это самостоятельно написанный ОБЩИЙ рендерер прямой линии с гауссовым свечением: '
            '15 измеренных чисел и редактируемые точки, сердцевина, размер ореола, яркость '
            'и Mix. Это НЕ алгоритм Saber и не перевод DLL. Проект AE не разбирался; целые '
            'кадры в WASM не входят. Результат ЗАМЕНЯЕТ непрозрачный слой лучом на чёрном фоне. '
            'Используйте Solid на размер композиции, иначе ореол обрежется по слою. '
            'Есть лишь два кадра разных размеров: независимость от входа, поведение альфа, '
            'смешивание, анимация и другие пресеты НЕ доказаны. Второй кадр дал пиксельную '
            'ошибку, но семейство лучей выбиралось с учётом этих примеров; для честной '
            'новой проверки нужен ещё один фон или другая форма/время. Маски, текст, '
            'мерцание, искажения, интерфейс AE и HDR не перенесены. Предел — 9 млн пикселей '
            'на кадр. Проверьте реальный рендер в настольном EffectCraft.\n')


def failure_report(info, fitted: BeamFit, language: str = 'ru') -> str:
    head = ('Line-glow model rejected; no WASM created' if language == 'en' else
            'Модель луча отклонена; WASM не создан')
    metrics = (f'check MAE {fitted.check_mae:.2f}/255, p95 {fitted.check_p95}/255'
               if fitted.check_mae is not None else 'model geometry not measurable')
    return (f'# {head}\n\n- AEX SHA-256 `{info.sha256}`\n'
            f'- {fitted.reason}\n- {metrics}\n\n'
            'A straight-line model is limited to one opaque preset without masks, text or '
            'animation. No AE DLL code or captured frame is copied into a fake effect.\n')
