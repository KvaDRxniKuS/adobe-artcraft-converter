"""The two data-only slots of the reusable measured line-glow WASM kernel.

No vendor .aex, reference PNG or user project enters the compiled template.
A candidate carries fifteen fitted Gaussian amplitudes plus its manifest.
"""
from __future__ import annotations

import math
import struct

from .lut_layout import manifest_bytes

SIGMAS = (3.0, 8.0, 25.0, 70.0, 220.0)  # Layer pixels, not screen pixels.
WEIGHT_COUNT = len(SIGMAS) * 3
SLOT_PREFIX = b'ARTCRAFT_BEAM_V1_BEGIN!'
SLOT_SUFFIX = b'!ARTCRAFT_BEAM_V1_END'
# A non-zero seed keeps AssemblyScript's data segment contiguous at build time.
TEMPLATE_WEIGHTS = struct.pack('<' + 'f' * WEIGHT_COUNT, *([1.0] * WEIGHT_COUNT))


def weight_bytes(rows) -> bytes:
    """RGB-major, five non-negative f32 amplitudes per channel (0..255 units)."""
    if len(rows) != 3 or any(len(row) != len(SIGMAS) for row in rows):
        raise ValueError('The beam model needs exactly 3 × 5 Gaussian amplitudes')
    values = [float(value) for row in rows for value in row]
    if any(not math.isfinite(value) or value < 0 or value > 512 for value in values):
        raise ValueError('Invalid measured beam amplitude')
    return struct.pack('<' + 'f' * WEIGHT_COUNT, *values)


def patch_wasm(base: bytes, template: dict, manifest: dict, weights: bytes) -> bytes:
    """Only patch the pre-reviewed binary's fixed data regions, never executable code."""
    if not isinstance(weights, bytes) or len(weights) != len(TEMPLATE_WEIGHTS):
        raise ValueError('Invalid beam coefficient size')
    old_meta, new_meta = manifest_bytes(template), manifest_bytes(manifest)
    old_slot = SLOT_PREFIX + TEMPLATE_WEIGHTS + SLOT_SUFFIX
    new_slot = SLOT_PREFIX + weights + SLOT_SUFFIX
    if base.count(old_meta) != 1 or base.count(old_slot) != 1:
        raise RuntimeError('Unexpected measured beam WASM layout; refusing to patch')
    output = base.replace(old_meta, new_meta, 1).replace(old_slot, new_slot, 1)
    if len(output) != len(base) or not output.startswith(b'\0asm'):
        raise RuntimeError('Corrupt measured beam WASM')
    return output
