#!/usr/bin/env python3
"""Build the reusable EffectCraft procedural line-glow WASM (developer-only).

npm install --prefix tools/.venv/wasm-tools --no-save assemblyscript@0.28.20
python3 tools/build_measured_line_glow.py --asc tools/.venv/wasm-tools/node_modules/.bin/asc
Neither a user frame nor any vendor .aex goes into the source or compiled template.
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
from craft_converter.beam_layout import (  # noqa: E402
    TEMPLATE_WEIGHTS, SLOT_PREFIX, SLOT_SUFFIX,
)
from craft_converter.lut_layout import MANIFEST_CAPACITY, manifest_bytes  # noqa: E402


def build(compiler: str) -> None:
    manifest = json.loads((ROOT / 'effectcraft_plugins/measured_line_glow_manifest.json').read_text(
        encoding='utf-8'))
    ids = [param['id'] for param in manifest['params']]
    if manifest['api'] != 1 or ids != [
            'start', 'end', 'core_radius', 'core_color', 'glow_size', 'intensity', 'mix']:
        raise ValueError('Unexpected measured line-glow manifest')
    meta = manifest_bytes(manifest)
    slot = SLOT_PREFIX + TEMPLATE_WEIGHTS + SLOT_SUFFIX
    template = (ROOT / 'effectcraft_plugins/measured_line_glow.ts.in').read_text(
        encoding='utf-8')
    for variable in ('__MANIFEST_BYTES__', '__SLOT_BYTES__', '__MANIFEST_LEN__', '__PREFIX_LEN__'):
        if template.count(variable) != 1:
            raise ValueError(f'Expected one {variable} in AssemblyScript template')
    source = (template.replace('__MANIFEST_BYTES__', ','.join(str(x) for x in meta))
              .replace('__SLOT_BYTES__', ','.join(str(x) for x in slot))
              .replace('__MANIFEST_LEN__', str(MANIFEST_CAPACITY))
              .replace('__PREFIX_LEN__', str(len(SLOT_PREFIX))))
    with tempfile.TemporaryDirectory(prefix='artcraft-line-') as folder:
        program, target = Path(folder) / 'line.ts', Path(folder) / 'line.wasm'
        program.write_text(source, encoding='utf-8')
        subprocess.run([compiler, str(program), '-o', str(target), '--runtime', 'stub',
                        '--noAssert', '--optimize'], check=True)
        wasm = target.read_bytes()
    if not wasm.startswith(b'\0asm') or not 5000 < len(wasm) < 512000:
        raise ValueError('AssemblyScript did not produce a small WASM module')
    if wasm.count(meta) != 1 or wasm.count(slot) != 1:
        raise ValueError('The compiler did not preserve the two fixed data slots')
    encoded = base64.b64encode(wasm).decode('ascii')
    lines = '\n'.join(f'    {part!r}' for part in textwrap.wrap(encoded, 100))
    module = ('"""Precompiled reusable procedural line-glow kernel, NOT Saber code.\n\n'
              'Only numeric Gaussian coefficients and manifest fields are fitted from PNGs.\n'
              'Built from effectcraft_plugins/measured_line_glow.ts.in.\n'
              '"""\nimport base64\nimport json\n\n'
              f'MANIFEST = json.loads({json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))!r})\n'
              f'WASM_SHA256 = {hashlib.sha256(wasm).hexdigest()!r}\n'
              f'WASM = base64.b64decode(\n{lines}\n)\n')
    path = ROOT / 'craft_converter/effectcraft_measured_beam.py'
    path.write_text(module, encoding='utf-8')
    print(f'Wrote {path} ({len(wasm)} bytes, sha256={hashlib.sha256(wasm).hexdigest()})')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--asc', default=shutil.which('asc'))
    args = parser.parse_args()
    if not args.asc:
        parser.error('Install assemblyscript@0.28.20 and pass --asc')
    build(args.asc)
