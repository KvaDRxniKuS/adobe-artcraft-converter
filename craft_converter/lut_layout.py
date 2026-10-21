"""Fixed ABI/data slots for independently written, measured EffectCraft LUTs.

The precompiled WASM contains an identity LUT and a padded JSON manifest. Only
these two *data* regions are replaced after a reference-frame fit; no Adobe
instructions, resources or license data are copied. A fixed layout also lets a
source-only update and a PyInstaller EXE export ports without npm or Node.js.
"""
from __future__ import annotations

import json

GRID = 17
LUT_SIZE = GRID ** 3 * 3
MANIFEST_CAPACITY = 4096
SLOT_PREFIX = b'ARTCRAFT_LUT_V1_BEGIN!'
SLOT_SUFFIX = b'!ARTCRAFT_LUT_V1_END'


def identity_lut() -> bytes:
    levels = [round(i * 255 / (GRID - 1)) for i in range(GRID)]
    return bytes(channel for r in levels for g in levels for b in levels
                 for channel in (r, g, b))


def manifest_bytes(manifest: dict) -> bytes:
    data = json.dumps(manifest, ensure_ascii=False, separators=(',', ':'),
                      allow_nan=False).encode('utf-8')
    if len(data) > MANIFEST_CAPACITY or manifest.get('api') != 1:
        raise ValueError('Measured effect manifest exceeds its reserved slot or has a wrong API')
    padded = data.ljust(MANIFEST_CAPACITY, b' ')
    if json.loads(padded) != manifest:
        raise ValueError('Invalid measured effect manifest')
    return padded


def patch_wasm(base: bytes, template: dict, manifest: dict, colour_table: bytes) -> bytes:
    """Replace only the unique manifest and colour-data slots in a trusted WASM."""
    if not isinstance(colour_table, bytes) or len(colour_table) != LUT_SIZE:
        raise ValueError('Measured colour LUT must have exactly 17^3 RGB entries')
    old_manifest, new_manifest = manifest_bytes(template), manifest_bytes(manifest)
    old_slot = SLOT_PREFIX + identity_lut() + SLOT_SUFFIX
    new_slot = SLOT_PREFIX + colour_table + SLOT_SUFFIX
    if base.count(old_manifest) != 1 or base.count(old_slot) != 1:
        raise RuntimeError('Unexpected measured WASM layout; refusing to patch')
    result = base.replace(old_manifest, new_manifest, 1).replace(old_slot, new_slot, 1)
    if len(result) != len(base) or not result.startswith(b'\0asm'):
        raise RuntimeError('Corrupt measured WASM template')
    return result
