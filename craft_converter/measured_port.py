"""Local, reference-driven porting for a bounded subset of unknown AE effects.

A fixed, independently coded EffectCraft renderer learns a 17^3 RGB LUT from
one colour chart and is checked against a DIFFERENT, untrained image. This can
approximate a pixel-local colour operation at ONE AE setting. It does not lift
or execute the .aex or learn spatial, temporal, alpha or HDR processing.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .effectcraft_measured_lut import MANIFEST as TEMPLATE_MANIFEST, WASM, WASM_SHA256
from .lut_layout import GRID, LUT_SIZE, identity_lut, patch_wasm

TRAIN_INPUT = 'chart_training_input.png'
CHECK_INPUT = 'chart_check_input.png'
TRAIN_AFTER = 'chart_training_ae.png'
CHECK_AFTER = 'chart_check_ae.png'
INSTRUCTIONS = 'HOW_TO_RENDER.txt'
REFERENCE_METADATA = 'reference.json'
REFERENCE_FORMAT = 'artcraft.measured-colour-reference'
PATCH = 12
COLUMNS = 71
ROWS = math.ceil(GRID ** 3 / COLUMNS)
CHECK_WIDTH = 256
CHECK_HEIGHT = 192
MAX_PNG_BYTES = 16 * 1024 * 1024
MAX_MEAN_ERROR = 6.0  # 8-bit RGB units: not a claim of AE equivalence.
MAX_P95_ERROR = 18

GUIDE = """Measured colour port / Мастер цветового порта

The two *_input.png charts and reference.json are bound to this .aex build.
Keep them UNCHANGED and do not reuse them with a different build.
In installed After Effects, import each chart as footage (no resizing, masks,
other effects or colour-management changes), place it on an OPAQUE composition
of exactly the chart's pixel dimensions, and apply the SAME .aex effect with
ONE fixed parameter preset to each. Export a PNG frame for each chart:
    chart_training_input.png -> chart_training_ae.png
    chart_check_input.png    -> chart_check_ae.png
Save the two rendered PNGs IN THIS FOLDER. Do not export JPG or scale the layer.
If the result changes size, alpha or space/time, the current wizard rejects it.
Keep your After Effects project if you want to remember the precise settings;
the .aep itself does not contain a portable renderer and is not read here.
Run the converter with --reference-dir pointing to THIS folder. It verifies
unseen colours/edges and writes a WASM only if the error is low enough. The
WASM has a Mix control, NOT the original AE parameter controls or animation.

Два файла *_input.png и reference.json привязаны к конкретному .aex; не меняйте
их и не используйте с другой сборкой. Импортируйте каждый PNG в
установленный After Effects, примените один и тот же .aex с ОДНИМИ настройками
на непрозрачной композиции точно такого же размера. Сохраните результат каждого
в PNG под именем chart_training_ae.png и chart_check_ae.png в ЭТУ ЖЕ папку.
Без масштаба, масок, других эффектов и смены цветового пространства. Проект
.aep полезен для хранения настроек, но сам алгоритм из него не извлекается.
Конвертер сравнит незнакомые цвета и границы; при большом расхождении WASM
не выдаётся. Этот порт передаёт только фиксированный вид эффекта + Mix.
"""


class ReferenceError(ValueError):
    """A measured port cannot be trusted or input is missing/unsafe."""


@dataclass(frozen=True)
class Fit:
    table: bytes
    mean_error: float
    p95_error: int
    observed_change: float
    alpha_error: float
    max_alpha_error: int
    hashes: tuple[str, str, str, str]  # Input/train, AE/train, input/check, AE/check.
    reason: str | None

    @property
    def accepted(self) -> bool:
        return self.reason is None


def _image_module():
    """Keep Pillow optional for other conversions and explain how to enable PNGs."""
    try:
        from PIL import Image
    except ImportError as exc:
        if getattr(sys, 'frozen', False):
            hint = ('Rebuild dist/FilmCraftConverter.exe from the latest sources with '
                    'Build_Windows_EXE.bat. / Пересоберите EXE из новых исходников.')
        else:
            requirements = Path(__file__).resolve().parents[1] / 'config/requirements.txt'
            hint = (f'Install into the Python running this converter: '
                    f'"{sys.executable}" -m pip install -r "{requirements}". '
                    'Use the same Python when starting the app. / '
                    'Установите зависимости в тот же Python, которым запущен конвертер.')
        raise RuntimeError(f'Pillow (Python module PIL) is required for PNG reference charts. '
                           f'{hint}') from exc
    return Image


def training_chart():
    Image = _image_module()
    image = Image.new('RGBA', (COLUMNS * PATCH, ROWS * PATCH), (32, 32, 32, 255))
    pixels = image.load()
    levels = [round(i * 255 / (GRID - 1)) for i in range(GRID)]
    for index in range(GRID ** 3):
        r, g, b = index // (GRID * GRID), (index // GRID) % GRID, index % GRID
        x0, y0 = (index % COLUMNS) * PATCH, (index // COLUMNS) * PATCH
        colour = (levels[r], levels[g], levels[b], 255)
        for y in range(y0, y0 + PATCH):
            for x in range(x0, x0 + PATCH):
                pixels[x, y] = colour
    return image


def check_chart():
    """Held-out gradients AND sharp edges catch purely spatial impostors."""
    Image = _image_module()
    image = Image.new('RGBA', (CHECK_WIDTH, CHECK_HEIGHT), (0, 0, 0, 255))
    pixels = image.load()
    for y in range(CHECK_HEIGHT):
        for x in range(CHECK_WIDTH):
            if x < CHECK_WIDTH // 2:
                value = ((x * 167 + y * 73) ^ (x * 11 + y * 29)) & 255
                rgb = ((x * 255 // (CHECK_WIDTH // 2 - 1)),
                       y * 255 // (CHECK_HEIGHT - 1), value)
            else:
                tile = (x // 4) * 741103597 + (y // 4) * 190997
                rgb = (tile & 255, (tile >> 8) & 255, (tile >> 16) & 255)
            pixels[x, y] = (*rgb, 255)
    return image


def prepare_charts(directory: Path, *, aex_digest: str) -> tuple[Path, Path]:
    """Create local calibration images bound to the chosen AEX binary identity."""
    if not isinstance(aex_digest, str) or re.fullmatch(r'[0-9a-f]{64}', aex_digest) is None:
        raise ReferenceError('A valid SHA-256 digest of the selected .aex is required.')
    directory = Path(directory)
    if (directory / 'Start_Converter.bat').exists():
        raise ReferenceError('Select a subfolder for references, not the repository root.')
    targets = [directory / TRAIN_INPUT, directory / CHECK_INPUT,
               directory / INSTRUCTIONS, directory / REFERENCE_METADATA]
    if any(path.exists() or path.is_symlink() for path in targets):
        raise FileExistsError('Reference charts or instructions already exist; choose an empty folder.')
    directory.mkdir(parents=True, exist_ok=True)
    created = []
    try:
        for path, image in ((targets[0], training_chart()), (targets[1], check_chart())):
            with path.open('xb') as stream:
                created.append(path)
                image.save(stream, format='PNG')
        with targets[2].open('x', encoding='utf-8') as out:
            created.append(targets[2])
            out.write(GUIDE)
        with targets[3].open('x', encoding='utf-8') as out:
            created.append(targets[3])
            json.dump({'format': REFERENCE_FORMAT, 'version': 1,
                       'aex_sha256': aex_digest}, out, indent=2)
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return targets[0], targets[1]


def _load_png(path: Path, size: tuple[int, int]):
    Image = _image_module()
    if not path.is_file():
        raise ReferenceError(f'Missing reference PNG: {path.name}. See {INSTRUCTIONS}.')
    if path.stat().st_size > MAX_PNG_BYTES:
        raise ReferenceError(f'Reference PNG is too large: {path.name}')
    try:
        with Image.open(path) as source:
            if source.format != 'PNG' or source.size != size:
                raise ReferenceError(f'{path.name}: expected an unscaled {size[0]}×{size[1]} PNG.')
            return source.convert('RGBA')
    except (OSError, ValueError) as exc:
        if isinstance(exc, ReferenceError):
            raise
        raise ReferenceError(f'Cannot read PNG {path.name}: {exc}') from exc


def _references(folder: Path, aex_digest: str):
    marker = folder / REFERENCE_METADATA
    try:
        if marker.stat().st_size > 4096:
            raise ReferenceError('Reference metadata is too large.')
        info = json.loads(marker.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError) as exc:
        if isinstance(exc, ReferenceError):
            raise
        raise ReferenceError(f'Missing/invalid {REFERENCE_METADATA}; prepare fresh charts for this AEX.') from exc
    if (not isinstance(info, dict) or info.get('format') != REFERENCE_FORMAT
            or info.get('version') != 1 or info.get('aex_sha256') != aex_digest):
        raise ReferenceError('Reference charts belong to another .aex build; prepare fresh charts.')
    before = training_chart()
    check = check_chart()
    training_source = _load_png(folder / TRAIN_INPUT, before.size)
    check_source = _load_png(folder / CHECK_INPUT, check.size)
    if training_source.tobytes() != before.tobytes() or check_source.tobytes() != check.tobytes():
        raise ReferenceError('Input charts were changed; prepare a new, unmodified reference folder.')
    return before, _load_png(folder / TRAIN_AFTER, before.size), check, _load_png(
        folder / CHECK_AFTER, check.size)


def render_rgb(table: bytes, rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """Python mirror of the WASM trilinear interpolation (for validation)."""
    cells = [min(GRID - 2, v * (GRID - 1) // 255) for v in rgb]
    frac = [v * (GRID - 1) / 255 - cell for v, cell in zip(rgb, cells)]
    colour = [0.0, 0.0, 0.0]
    for dr in (0, 1):
        rw = frac[0] if dr else 1.0 - frac[0]
        for dg in (0, 1):
            gw = frac[1] if dg else 1.0 - frac[1]
            for db in (0, 1):
                bw = frac[2] if db else 1.0 - frac[2]
                slot = (((cells[0] + dr) * GRID + cells[1] + dg) * GRID + cells[2] + db) * 3
                weight = rw * gw * bw
                for channel in range(3):
                    colour[channel] += table[slot + channel] * weight
    return tuple(round(v) for v in colour)


def fit(folder: Path, aex_digest: str) -> Fit:
    """Measure chart centres, then reject a model that fails held-out pixels."""
    folder = Path(folder)
    before, after, check, result = _references(folder, aex_digest)
    hashes = []
    for name in (TRAIN_INPUT, TRAIN_AFTER, CHECK_INPUT, CHECK_AFTER):
        with (folder / name).open('rb') as stream:
            data = stream.read(MAX_PNG_BYTES + 1)
        if len(data) > MAX_PNG_BYTES:
            raise ReferenceError(f'Reference PNG is too large: {name}')
        hashes.append(hashlib.sha256(data).hexdigest())
    pixels = after.load()
    # The table has no alpha component. Check the entire training frame, not
    # just patch centres, so a localized transparency change cannot slip through.
    min_alpha, _ = after.getchannel('A').getextrema()
    max_alpha = 255 - min_alpha
    values = bytearray(LUT_SIZE)
    for index in range(GRID ** 3):
        cx = (index % COLUMNS) * PATCH + PATCH // 2
        cy = (index // COLUMNS) * PATCH + PATCH // 2
        for c in range(3):
            values[index * 3 + c] = round(sum(pixels[cx + dx, cy + dy][c]
                                              for dx in (-1, 0, 1)
                                              for dy in (-1, 0, 1)) / 9)
    table = bytes(values)
    source, target = check.load(), result.load()
    histogram = [0] * 256
    error = change = alpha = 0
    count = CHECK_WIDTH * CHECK_HEIGHT
    for y in range(CHECK_HEIGHT):
        for x in range(CHECK_WIDTH):
            old, actual = source[x, y], target[x, y]
            prediction = render_rgb(table, old[:3])
            for c in range(3):
                distance = abs(prediction[c] - actual[c])
                histogram[distance] += 1
                error += distance
                change += abs(old[c] - actual[c])
            alpha_diff = abs(old[3] - actual[3])
            alpha += alpha_diff
            max_alpha = max(max_alpha, alpha_diff)
    percent = math.ceil(count * 3 * 0.95)
    accumulated = 0
    p95 = 255
    for distance, frequency in enumerate(histogram):
        accumulated += frequency
        if accumulated >= percent:
            p95 = distance
            break
    mae = error / (count * 3)
    changed = change / (count * 3)
    alpha_mae = alpha / count
    reason = None
    if max_alpha > 2 or alpha_mae > 1.0:
        reason = 'The AE reference changes transparency; this RGB-only port preserves alpha.'
    elif changed < 1.5:
        reason = 'The AE effect made no measurable change on the independent chart.'
    elif mae > MAX_MEAN_ERROR or p95 > MAX_P95_ERROR:
        reason = ('Reference mismatch: the effect may use blur, sorting, masks, time, '
                  'neighbouring pixels, HDR or another unsupported operation.')
    return Fit(table, mae, p95, changed, alpha_mae, max_alpha,
               tuple(hashes), reason)


def build_port(aex_digest: str, name: str, fitted: Fit) -> tuple[bytes, dict]:
    if not fitted.accepted:
        raise ReferenceError(fitted.reason or 'Reference validation failed')
    if hashlib.sha256(WASM).hexdigest() != WASM_SHA256:
        raise RuntimeError('Embedded EffectCraft measured renderer is corrupt')
    # Bind this effect id to the exact AE renders already validated by fit().
    preset_digest = hashlib.sha256((fitted.hashes[1] + fitted.hashes[3]).encode('ascii')).hexdigest()
    manifest = json.loads(json.dumps(TEMPLATE_MANIFEST))
    manifest['id'] = 'org.artcraft_converter.measured.' + hashlib.sha256(
        (aex_digest + preset_digest).encode('ascii')).hexdigest()[:24]
    safe_name = ''.join(char if char.isprintable() else ' ' for char in name).strip()
    manifest['name'] = (safe_name[:48] or 'AE colour effect') + ' (measured)'
    manifest['description'] = ('Measured 3D colour LUT from AE PNG reference frames at ONE fixed '
                               'setting; Mix only. No .aex code; no spatial, alpha, HDR or temporal processing. '
                               f'Check MAE {fitted.mean_error:.2f}/255, p95 {fitted.p95_error}/255.')
    return patch_wasm(WASM, TEMPLATE_MANIFEST, manifest, fitted.table), manifest


def report_text(source: Path, output: Path, info, manifest: dict, fitted: Fit,
                language: str = 'ru') -> str:
    hashes = '\n'.join(f'- `{filename}` SHA-256: `{digest}`'
                       for filename, digest in zip(
                           (TRAIN_INPUT, TRAIN_AFTER, CHECK_INPUT, CHECK_AFTER), fitted.hashes))
    if language == 'en':
        return (f'# Measured AE colour effect → EffectCraft (experimental)\n\n'
                f'- AEX: `{source.name}`, SHA-256 `{info.sha256}`; PE {info.architecture}\n'
                f'- WASM: `{output.name}`; effect ID `{manifest["id"]}`\n'
                f'- Observed change: {fitted.observed_change:.2f}/255; '
                f'held-out MAE: {fitted.mean_error:.2f}/255; '
                f'95th percentile: {fitted.p95_error}/255; alpha error: {fitted.alpha_error:.2f}/255; '
                f'max alpha error: {fitted.max_alpha_error}/255\n'
                f'{hashes}\n\n'
                'The DLL was read for identity only. The independent WASM implements a measured '
                '17×17×17 RGB 3D LUT fitted from PNG frames rendered by the user in AE at ONE '
                'setting. This is NOT machine-code translation, nor proven visual equivalence. '
                'No AE parameters, keyframes, masks, spatial/temporal effects, HDR or alpha '
                'processing are ported. The only exposed control is Mix; other colour profiles '
                'and inputs may differ. Alpha is preserved and RGB is premultiplied in EffectCraft. '
                'This kernel renders frames up to 9 million pixels. If the DLL contains '
                'multiple effects, its PiPL list does not prove which one was used in AE. '
                'Test in EffectCraft desktop before relying on it.\n')
    return (f'# Измеренный цветовой эффект AE → EffectCraft (экспериментально)\n\n'
            f'- AEX: `{source.name}`, SHA-256 `{info.sha256}`; PE {info.architecture}\n'
            f'- WASM: `{output.name}`; ID эффекта `{manifest["id"]}`\n'
            f'- Изменение в AE: {fitted.observed_change:.2f}/255; '
            f'средняя ошибка на незнакомых пикселях: {fitted.mean_error:.2f}/255; '
            f'95-й процентиль: {fitted.p95_error}/255; ошибка альфа: {fitted.alpha_error:.2f}/255; '
            f'максимальная ошибка альфа: {fitted.max_alpha_error}/255\n'
            f'{hashes}\n\n'
            'DLL читалась только для идентификации. Самостоятельный WASM содержит измеренную '
            '3D-таблицу RGB 17×17×17 по PNG-кадрам, экспортированным пользователем из AE '
            'при ОДНИХ настройках. Это НЕ перевод машинного кода и НЕ подтверждение точного '
            'совпадения. Параметры AE, ключевые кадры, маски, пространственные и временные '
            'эффекты, HDR и обработка альфы не перенесены. Управление только Mix; на других '
            'кадрах/цветовых профилях результат может отличаться. Альфа сохраняется, RGB в '
            'EffectCraft хранится с предумножением. Предел кадра — 9 миллионов пикселей. Если DLL содержит несколько эффектов, '
            'список PiPL не подтверждает, какой из них применялся в AE. '
            'Проверьте WASM в настольном EffectCraft.\n')


def failure_report(info, fitted: Fit, language: str = 'ru') -> str:
    heading = ('Reference-driven port was rejected; no WASM created' if language == 'en' else
               'Мастер отклонил порт; WASM не создан')
    translations = {
        'The AE reference changes transparency; this RGB-only port preserves alpha.':
            'Результат AE меняет прозрачность; измеренный RGB-порт сохраняет альфа-канал.',
        'The AE effect made no measurable change on the independent chart.':
            'Эффект AE не изменил независимую проверочную картинку заметным образом.',
        ('Reference mismatch: the effect may use blur, sorting, masks, time, '
         'neighbouring pixels, HDR or another unsupported operation.'):
            'Большое расхождение: возможны размытие, сортировка, маски, время, '
            'соседние пиксели, HDR или другой неподдерживаемый алгоритм.',
    }
    mismatch = bool(fitted.reason and fitted.reason.startswith('Reference mismatch:'))
    if language == 'en':
        detail = (
            'A large change to the original picture is NOT why this attempt was rejected: '
            'the LUT prediction disagrees with the independent AE render. A solid-colour '
            'replacement could pass; a position/mask/time-dependent generator generally '
            'cannot be represented by a colour-only LUT. Two charts of DIFFERENT sizes '
            'cannot establish whether the effect ignores its input.\n\n'
            'To investigate a generator, provide a minimal AE project with its core path '
            'or mask and settings, plus before/after PNGs for TWO different backgrounds at '
            'the SAME canvas size, preset and time. Include a changed core/path or another '
            'time if animation matters. These references help design and validate an '
            'independent procedural renderer; they cannot turn the DLL into WASM automatically.\n'
        ) if mismatch else (
            'This wizard can fit only fixed-setting, pixel-local 8-bit RGB operations; '
            'other effects require a separately tested renderer.\n'
        )
        return (f'# {heading}\n\n'
                f'- AEX SHA-256: `{info.sha256}`\n'
                f'- {fitted.reason}\n'
                f'- Held-out RGB MAE: {fitted.mean_error:.2f}/255 (limit {MAX_MEAN_ERROR:g}); '
                f'p95: {fitted.p95_error}/255 (limit {MAX_P95_ERROR}); '
                f'input-to-AE change: {fitted.observed_change:.2f}/255; '
                f'alpha MAE: {fitted.alpha_error:.2f}/255; '
                f'max alpha error: {fitted.max_alpha_error}/255.\n\n'
                f'{detail}')
    reason = translations.get(fitted.reason, fitted.reason) + f' ({fitted.reason})'
    detail = (
        'Большое изменение исходной картинки само по себе НЕ причина отказа: '
        'предсказание цветовой таблицы сильно отличается от независимого рендера AE. '
        'Сплошная заливка могла бы пройти проверку; генератор, зависящий от координат, '
        'маски или времени, нельзя представить только таблицей цвета. Две картинки '
        'РАЗНОГО размера не позволяют выяснить, зависит ли эффект от входа.\n\n'
        'Для исследования генератора нужен минимальный проект AE с формой сердцевины '
        'или маской и настройками, а также PNG до/после на ДВУХ разных фонах при '
        'ОДИНАКОВЫХ размере композиции, настройках и времени. Если важна анимация, '
        'добавьте другую форму/положение сердцевины или другое время. Эти примеры '
        'помогут разработать и проверить отдельный процедурный рендерер, но сами '
        'по себе не превращают DLL в WASM автоматически.\n'
    ) if mismatch else (
        'Мастер подбирает только попиксельные преобразования 8-битного RGB при '
        'фиксированных настройках; остальные эффекты требуют отдельного проверенного рендерера.\n'
    )
    return (f'# {heading}\n\n'
            f'- AEX SHA-256: `{info.sha256}`\n'
            f'- {reason}\n'
            f'- RGB: средняя ошибка на проверке {fitted.mean_error:.2f}/255 '
            f'(допуск {MAX_MEAN_ERROR:g}); 95-й процентиль {fitted.p95_error}/255 '
            f'(допуск {MAX_P95_ERROR}); изменение входа в AE '
            f'{fitted.observed_change:.2f}/255; средняя ошибка альфа '
            f'{fitted.alpha_error:.2f}/255, максимальная '
            f'{fitted.max_alpha_error}/255.\n\n'
            f'{detail}')
