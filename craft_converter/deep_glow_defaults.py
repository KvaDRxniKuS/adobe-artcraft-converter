"""Safe, compiler-free default slots in the *independent* Deep Glow WASM.

The builder leaves fixed-width JSON whitespace after each manifest default. JSON
parsers ignore the spaces, but they let the converter substitute user-exported
AE numbers without changing WASM section sizes, addresses or code. This changes
only defaults used for NEW EffectCraft instances; the render algorithm and old
project instances are untouched. It never edits or executes an Adobe binary.
"""
from __future__ import annotations

import copy
import json
import math
import re
from collections.abc import Mapping

DEFAULT_SLOT_WIDTH = 32
_NUMBER = r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?'


def padded_manifest(manifest: dict) -> bytes:
    """Serialize this known manifest with fixed-width scalar default tokens."""
    text = json.dumps(manifest, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    for param in manifest['params']:
        pid = json.dumps(param['id'], ensure_ascii=False)
        pattern = re.compile(r'(\{"id":' + re.escape(pid)
                             + r',[^{}]*?"default":)(true|false|' + _NUMBER + r')(?=[,}])')
        matches = list(pattern.finditer(text))
        if len(matches) != 1:
            raise ValueError(f'Missing or ambiguous Deep Glow default: {param["id"]}')
        match = matches[0]
        token = match.group(2)
        if len(token) > DEFAULT_SLOT_WIDTH:
            raise ValueError(f'Deep Glow default does not fit reserved slot: {param["id"]}')
        text = text[:match.start(2)] + token.ljust(DEFAULT_SLOT_WIDTH) + text[match.end(2):]
    result = text.encode('utf-8')
    if json.loads(result) != manifest:
        raise ValueError('Invalid Deep Glow manifest serialization')
    return result


def customized_wasm(base: bytes, original: dict, defaults: Mapping[str, float]) -> tuple[bytes, dict]:
    """Replace exactly one embedded manifest, after validating every override.

    Only the compiler-produced base WASM should be passed here; the caller checks
    its SHA-256 against the packaged asset. The new module has exactly the same
    length and machine instructions, so the v1 ABI and memory layout stay put.
    """
    if not isinstance(defaults, Mapping):
        raise ValueError('Deep Glow defaults must be a mapping of parameter ids to values')
    manifest = copy.deepcopy(original)
    by_id = {p['id']: p for p in manifest['params']}
    for pid, value in defaults.items():
        if pid not in by_id:
            raise ValueError(f'Unknown Deep Glow parameter: {pid}')
        param = by_id[pid]
        if param['type'] == 'checkbox':
            if type(value) is not bool:
                raise ValueError(f'Deep Glow {pid} must be boolean')
        elif param['type'] == 'popup':
            if type(value) is not int or not 0 <= value < len(param['options']):
                raise ValueError(f'Deep Glow {pid} must be a valid popup index')
        elif param['type'] == 'slider':
            try:
                finite = math.isfinite(value) if not isinstance(value, bool) else False
            except (OverflowError, TypeError):
                finite = False
            if not isinstance(value, (float, int)) or not finite:
                raise ValueError(f'Deep Glow {pid} must be a finite number')
            if not param['min'] <= value <= param['max']:
                raise ValueError(f'Deep Glow {pid} is outside the port range')
        else:
            raise ValueError(f'Unsupported Deep Glow parameter type: {pid}')
        param['default'] = value
    if not defaults:
        return base, manifest
    old = padded_manifest(original)
    new = padded_manifest(manifest)
    if len(new) != len(old) or base.count(old) != 1:
        raise RuntimeError('Unexpected Deep Glow WASM manifest layout; refusing to patch binary')
    patched = base.replace(old, new, 1)
    if len(patched) != len(base):
        raise RuntimeError('Deep Glow WASM size changed unexpectedly')
    return patched, manifest
