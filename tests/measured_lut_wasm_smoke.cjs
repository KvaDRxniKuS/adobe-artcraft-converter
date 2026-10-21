// Test converter-fitted invert and cross-channel colour effects in a real VM.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const file = process.argv[2];
const effect = process.argv[3] || 'invert';
assert.ok(file, 'pass the measured WASM file to smoke-test');
assert.ok(['invert', 'cross-channel', 'solid'].includes(effect));
const module_ = new WebAssembly.Module(fs.readFileSync(file));
assert.deepEqual(WebAssembly.Module.imports(module_), []);
const e = new WebAssembly.Instance(module_, {}).exports;
for (const name of ['ec_api_version', 'ec_manifest_ptr', 'ec_manifest_len',
                    'ec_alloc', 'ec_render', 'memory']) assert.ok(e[name], name);
assert.equal(e.ec_api_version(), 1);
const manifest = JSON.parse(Buffer.from(e.memory.buffer, e.ec_manifest_ptr(),
                                        e.ec_manifest_len()).toString('utf8'));
assert.equal(manifest.api, 1);
assert.match(manifest.name, /measured/);
assert.equal(manifest.params.length, 1);
assert.equal(manifest.params[0].id, 'mix');
const size = 3 * 16;
const base = e.ec_alloc(8 + size);
assert.ok(base > e.ec_manifest_ptr() + e.ec_manifest_len());
const view = new DataView(e.memory.buffer);
const p = base + 8;
const samples = [[0.2, 0.4, 0.8, 1], [0.1, 0.2, 0.4, 0.5], [1, 0.5, 0, 1]];
function render(mix) {
  view.setFloat64(base, mix, true);
  samples.forEach((sample, i) => sample.forEach((n, c) =>
    view.setFloat32(p + i * 16 + c * 4, n, true)));
  assert.equal(e.ec_render(p, 3, 1, base, 1, 0, 1), 0);
  return samples.map((_, i) => Array.from({length: 4}, (_, c) =>
    view.getFloat32(p + i * 16 + c * 4, true)));
}
function close(actual, expected) { assert.ok(Math.abs(actual - expected) <= 0.006,
                                           `${actual} != ${expected}`); }
function colour(r, g, b) {
  if (effect === 'invert') return [1 - r, 1 - g, 1 - b];
  if (effect === 'solid') return [180 / 255, 30 / 255, 225 / 255];
  return [0.75 * r + 0.25 * g, 0.5 * r + 0.5 * b, 0.3 * g + 0.7 * b];
}
const expected = samples.map(([r, g, b, a]) =>
  [...colour(r / a, g / a, b / a).map(value => value * a), a]);
for (const mix of [100, 50, 0]) {
  const out = render(mix);
  expected.forEach((pixel, i) => pixel.forEach((value, c) =>
    close(out[i][c], (mix / 100) * value + (1 - mix / 100) * samples[i][c])));
}
assert.notEqual(e.ec_render(p, 0, 1, base, 1, 0, 1), 0);
console.log(`PASS: fitted ${effect} LUT WASM; opaque/translucent RGB, alpha, Mix`);
