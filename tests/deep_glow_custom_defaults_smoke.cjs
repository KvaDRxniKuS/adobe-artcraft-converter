// Load a converter-patched WASM (given as argv[2]) in the real JS WASM VM.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const file = process.argv[2];
assert.ok(file, 'pass path to customized WASM');
const module_ = new WebAssembly.Module(fs.readFileSync(file));
assert.deepEqual(WebAssembly.Module.imports(module_), []);
const e = new WebAssembly.Instance(module_, {}).exports;
assert.equal(e.ec_api_version(), 1);
const manifest = JSON.parse(Buffer.from(e.memory.buffer,
  e.ec_manifest_ptr(), e.ec_manifest_len()).toString('utf8'));
const parameters = manifest.params;
assert.equal(parameters.find(p => p.id === 'radius').default, 512);
assert.equal(parameters.find(p => p.id === 'threshold').default, 42);
assert.equal(parameters.find(p => p.id === 'blend_mode').default, 0);
const w = 31, h = 31, n = w * h;
const start = e.ec_alloc(parameters.length * 8 + n * 16);
assert.ok(start > e.ec_manifest_ptr() + e.ec_manifest_len());
const pix = start + parameters.length * 8;
const input = new DataView(e.memory.buffer);
for (let i = 0; i < parameters.length; i++) {
  input.setFloat64(start + i * 8, Number(parameters[i].default), true);
}
const center = pix + (15 * w + 15) * 16;
for (const c of [0, 1, 2, 3]) input.setFloat32(center + c * 4, 1, true);
assert.equal(e.ec_render(pix, w, h, start, parameters.length, 0, 1), 0);
const out = new DataView(e.memory.buffer);
assert.ok(out.getFloat32(pix + (15 * w + 16) * 16, true) > 0);
console.log('PASS: converter-patched WASM parses and renders with updated defaults');
