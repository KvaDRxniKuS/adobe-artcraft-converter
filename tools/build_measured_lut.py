#!/usr/bin/env python3
"""Build the generic, compiler-free-at-runtime EffectCraft measured-LUT kernel.

Developer-only: npm install --prefix tools/.venv/wasm-tools --no-save assemblyscript@0.28.20
python3 tools/build_measured_lut.py --asc tools/.venv/wasm-tools/node_modules/.bin/asc
No third-party .aex binary or proprietary code enters this source or build.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from craft_converter.lut_layout import (  # noqa: E402
    MANIFEST_CAPACITY, SLOT_PREFIX, SLOT_SUFFIX, identity_lut, manifest_bytes,
)


def build(compiler: str) -> None:
    manifest = json.loads((ROOT / 'effectcraft_plugins/measured_color_lut_manifest.json').read_text(
        encoding='utf-8'))
    if (manifest.get('api') != 1 or len(manifest.get('params', [])) != 1
            or manifest['params'][0]['id'] != 'mix'):
        raise ValueError('Unexpected measured LUT manifest')
    meta = manifest_bytes(manifest)
    slot = SLOT_PREFIX + identity_lut() + SLOT_SUFFIX
    template = (ROOT / 'effectcraft_plugins/measured_color_lut.ts.in').read_text(encoding='utf-8')
    for variable in ('__MANIFEST_BYTES__', '__SLOT_BYTES__', '__MANIFEST_LEN__', '__PREFIX_LEN__'):
        if template.count(variable) != 1:
            raise ValueError(f'Expected one {variable} in the AssemblyScript template')
    source = (template.replace('__MANIFEST_BYTES__', ','.join(str(x) for x in meta))
              .replace('__SLOT_BYTES__', ','.join(str(x) for x in slot))
              .replace('__MANIFEST_LEN__', str(MANIFEST_CAPACITY))
              .replace('__PREFIX_LEN__', str(len(SLOT_PREFIX))))
    with tempfile.TemporaryDirectory(prefix='artcraft-lut-') as folder:
        program, target = Path(folder) / 'measured.ts', Path(folder) / 'measured.wasm'
        program.write_text(source, encoding='utf-8')
        subprocess.run([compiler, str(program), '-o', str(target), '--runtime', 'stub',
                        '--noAssert', '--optimize'], check=True)
        wasm = target.read_bytes()
    if not wasm.startswith(b'\0asm') or not 10000 < len(wasm) < 512000:
        raise ValueError('AssemblyScript did not produce a small valid WASM module')
    if wasm.count(meta) != 1 or wasm.count(slot) != 1:
        raise ValueError('The compiler did not preserve the two fixed data slots')
    encoded = base64.b64encode(wasm).decode('ascii')
    lines = '\n'.join(f'    {part!r}' for part in textwrap.wrap(encoded, 100))
    module = ('"""Embedded independently written EffectCraft measured 3D LUT kernel.\n\n'
              'Built from effectcraft_plugins/measured_color_lut.ts.in. The inputs\n'
              'to local fitting are PNG frames; .aex code is never copied or run.\n'
              '"""\nimport base64\nimport json\n\n'
              f'MANIFEST = json.loads({json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))!r})\n'
              f'WASM_SHA256 = {hashlib.sha256(wasm).hexdigest()!r}\n'
              f'WASM = base64.b64decode(\n{lines}\n)\n')
    path = ROOT / 'craft_converter/effectcraft_measured_lut.py'
    path.write_text(module, encoding='utf-8')
    print(f'Wrote {path} ({len(wasm)} bytes, sha256={hashlib.sha256(wasm).hexdigest()})')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--asc', default=shutil.which('asc'))
    args = parser.parse_args()
    if not args.asc:
        parser.error('Install assemblyscript@0.28.20 and pass --asc')
    build(args.asc)
