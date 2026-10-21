#!/usr/bin/env python3
"""Rebuild the independent Deep Glow-like EffectCraft WASM and Python asset.

Only this development command needs AssemblyScript 0.28.20 and Node.js. The
converter never compiles, executes or bundles the supplied Adobe .aex.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'effectcraft_plugins/deep_glow_manifest.json'
TEMPLATE = ROOT / 'effectcraft_plugins/deep_glow.ts.in'
WASM_FILE = ROOT / 'effectcraft_plugins/DeepGlow_EffectCraft.wasm'
PYTHON_FILE = ROOT / 'craft_converter/effectcraft_deep_glow.py'


def build(compiler: str) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    params = manifest.get('params', [])
    if (manifest.get('api') != 1 or manifest.get('id') != 'org.artcraft_converter.deep_glow'
            or len(params) != 14 or len({p['id'] for p in params}) != 14):
        raise ValueError('Unexpected Deep Glow plug-in manifest.')
    compact = json.dumps(manifest, separators=(',', ':'), ensure_ascii=False)
    meta = compact.encode('utf-8')
    if len(meta) >= 60_000:
        raise ValueError('Manifest would overlap the host buffer.')
    source = TEMPLATE.read_text(encoding='utf-8')
    if source.count('__MANIFEST_BYTES__') != 1 or source.count('__MANIFEST_LEN__') != 1:
        raise ValueError('Missing/duplicate manifest placeholders.')
    array = ',\n  '.join(', '.join(str(x) for x in meta[i:i + 20])
                          for i in range(0, len(meta), 20))
    source = source.replace('__MANIFEST_BYTES__', array).replace('__MANIFEST_LEN__', str(len(meta)))
    with tempfile.TemporaryDirectory(prefix='deep-glow-build-') as temp:
        program = Path(temp) / 'deep_glow.ts'
        wasm = Path(temp) / 'deep_glow.wasm'
        program.write_text(source, encoding='utf-8')
        subprocess.run([compiler, str(program), '-o', str(wasm), '--runtime', 'stub',
                        '--noAssert', '--optimize'], check=True)
        payload = wasm.read_bytes()
        if not payload.startswith(b'\0asm') or len(payload) > 512_000:
            raise ValueError('Compiler did not produce a small WebAssembly module.')
        if shutil.which('node'):
            check = '''const fs=require('fs'),m=new WebAssembly.Module(fs.readFileSync(process.argv[1]));
if(WebAssembly.Module.imports(m).length)throw Error('EffectCraft forbids imports');
const e=new WebAssembly.Instance(m,{}).exports;
for(const n of ['memory','ec_api_version','ec_manifest_ptr','ec_manifest_len','ec_alloc','ec_render'])
if(!e[n])throw Error('Missing '+n);
if(e.ec_api_version()!==1)throw Error('Wrong API version');
const manifest=Buffer.from(e.memory.buffer,e.ec_manifest_ptr(),e.ec_manifest_len()).toString('utf8');
if(manifest!==process.argv[2])throw Error('Manifest mismatch');'''
            subprocess.run(['node', '-e', check, str(wasm), compact], check=True)
    encoded = base64.b64encode(payload).decode('ascii')
    lines = '\n'.join(f'    {line!r}' for line in textwrap.wrap(encoded, 100))
    body = ('"""Independent multi-scale glow effect for EffectCraft (API v1).\n\n'
            'Generated from effectcraft_plugins/deep_glow.ts.in by tools/build_deep_glow.py.\n'
            'No supplied Adobe code or binary is embedded or executed here.\n'
            '"""\n'
            'import base64\n'
            'import json\n\n'
            f'MANIFEST = json.loads({compact!r})\n'
            f'MANIFEST_SHA256 = {hashlib.sha256(meta).hexdigest()!r}\n'
            f'WASM_SHA256 = {hashlib.sha256(payload).hexdigest()!r}\n'
            'WASM = base64.b64decode(\n'
            f'{lines}\n'
            ')\n')
    WASM_FILE.write_bytes(payload)
    PYTHON_FILE.write_text(body, encoding='utf-8')
    print(f'Generated {WASM_FILE.name} ({len(payload)} bytes, sha256={hashlib.sha256(payload).hexdigest()})')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--asc', default=shutil.which('asc'),
                        help='AssemblyScript asc compiler (version 0.28.20)')
    args = parser.parse_args()
    if not args.asc:
        parser.error('Install assemblyscript@0.28.20 under .venv/wasm-tools and pass --asc')
    build(args.asc)


if __name__ == '__main__':
    main()
