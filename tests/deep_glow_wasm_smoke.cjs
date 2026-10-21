// Real WebAssembly execution of the independent Deep Glow-like EffectCraft effect.
// node tests/deep_glow_wasm_smoke.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const wasm = fs.readFileSync(path.join(__dirname, '..', 'effectcraft_plugins', 'DeepGlow_EffectCraft.wasm'));
const module_ = new WebAssembly.Module(wasm);
assert.deepEqual(WebAssembly.Module.imports(module_), [], 'EffectCraft forbids imports');
for (const name of ['memory', 'ec_api_version', 'ec_manifest_ptr', 'ec_manifest_len', 'ec_alloc', 'ec_render']) {
  assert.ok(WebAssembly.Module.exports(module_).some(x => x.name === name), `missing ${name}`);
}
const instance = new WebAssembly.Instance(module_, {}).exports;
assert.equal(instance.ec_api_version(), 1);
const manifest = JSON.parse(Buffer.from(instance.memory.buffer,
  instance.ec_manifest_ptr(), instance.ec_manifest_len()).toString('utf8'));
assert.equal(manifest.id, 'org.artcraft_converter.deep_glow');
assert.equal(manifest.api, 1);
assert.equal(manifest.params.length, 14);
const index = Object.fromEntries(manifest.params.map((p, n) => [p.id, n]));

function render(pixels, width, height, overrides = {}, scale = 1, time = 0) {
  assert.equal(pixels.length, width * height);
  const e = new WebAssembly.Instance(module_, {}).exports;
  const params = manifest.params.map(p => Number(p.default));
  for (const [key, value] of Object.entries(overrides)) {
    assert.ok(key in index, `unknown control: ${key}`);
    params[index[key]] = Number(value);
  }
  const base = e.ec_alloc(params.length * 8 + width * height * 16);
  assert.ok(base > e.ec_manifest_ptr() + e.ec_manifest_len());
  assert.equal(base % 8, 0);
  const img = base + params.length * 8;
  let view = new DataView(e.memory.buffer);
  params.forEach((n, k) => view.setFloat64(base + k * 8, n, true));
  pixels.forEach((px, n) => px.forEach((v, c) => view.setFloat32(img + n * 16 + c * 4, v, true)));
  assert.equal(e.ec_render(img, width, height, base, params.length, time, scale), 0);
  view = new DataView(e.memory.buffer); // memory.grow invalidates the old DataView
  return pixels.map((_, n) => Array.from({length: 4}, (_u, c) =>
    view.getFloat32(img + n * 16 + c * 4, true)));
}
function nearly(actual, expected, tolerance = 0.00001) {
  assert.ok(Math.abs(actual - expected) < tolerance, `${actual} != ${expected}`);
}
function impulse(w, h, x, y, rgba = [1, 1, 1, 1]) {
  const pixels = Array.from({length: w * h}, () => [0, 0, 0, 0]);
  pixels[y * w + x] = rgba;
  return pixels;
}

const w = 19, h = 19, cx = 9, cy = 9;
const image = impulse(w, h, cx, cy);
const controls = {radius: 3, exposure: 0, threshold: 50, threshold_smooth: 0, quality: 2};
const output = render(image, w, h, controls);
assert.ok(output[cy * w + cx][0] > 1);
assert.ok(output[cy * w + cx + 1][0] > 0);
assert.ok(output[cy * w + cx + 1][0] > output[cy * w + cx + 5][0]);
nearly(output[cy * w + cx - 1][0], output[cy * w + cx + 1][0]);
nearly(output[(cy - 1) * w + cx][0], output[(cy + 1) * w + cx][0]);
assert.ok(output[cy * w + cx + 1][3] > 0, 'glow expands transparent alpha');
for (const p of output) {
  assert.ok(p.every(Number.isFinite));
  assert.ok(p[3] >= 0 && p[3] <= 1);
}
assert.deepEqual(render(image, w, h, controls), output, 'render must be deterministic');
assert.deepEqual(render(image, w, h, {...controls, mix: 0}), image,
                 '0% glow mix must preserve premultiplied input');
const noAlpha = render(image, w, h, {...controls, expand_alpha: 0});
assert.equal(noAlpha[cy * w + cx + 1][3], 0);
assert.ok(noAlpha[cy * w + cx + 1][0] > 0);

const dim = impulse(w, h, cx, cy, [0.3, 0.3, 0.3, 1]);
const underThreshold = render(dim, w, h, {...controls, threshold: 90});
underThreshold.forEach((px, i) => px.forEach((v, c) => nearly(v, dim[i][c])));
const tinted = render(image, w, h, {...controls, tint_amount: 100,
                                    tint_red: 2, tint_green: 0, tint_blue: 0});
assert.ok(tinted[cy * w + cx + 1][0] > 0);
nearly(tinted[cy * w + cx + 1][1], 0);
nearly(tinted[cy * w + cx + 1][2], 0);
const onlyGlow = render(image, w, h, {...controls, blend_mode: 2});
assert.ok(onlyGlow[cy * w + cx][0] > 0 && onlyGlow[cy * w + cx][0] < 1);
const screen = render(image, w, h, {...controls, blend_mode: 1});
assert.ok(screen[cy * w + cx][0] <= 1.00001);
assert.ok(screen[cy * w + cx + 1][0] > 0);
const lowExposure = render(image, w, h, {...controls, exposure: -3});
assert.ok(output[cy * w + cx + 1][0] > lowExposure[cy * w + cx + 1][0]);
const draft = render(image, w, h, {...controls, quality: 0, radius: 12});
const high = render(image, w, h, {...controls, quality: 2, radius: 12});
assert.ok(high[cy * w + cx + 7][0] > draft[cy * w + cx + 7][0], 'more scales spread further');

// Premultiplied transparent input must never emit light. Soft-knee, tiny frames,
// high bit depth and variable preview scale are also exercised.
const half = impulse(7, 5, 3, 2, [0.5, 0.25, 0.1, 0.5]);
const semitransparent = render(half, 7, 5, {radius: 2, threshold: 0, threshold_smooth: 30});
assert.ok(semitransparent[2 * 7 + 2][0] > 0);
assert.ok(semitransparent[0].every(Number.isFinite));
render([[0.9, 0.9, 0.9, 0]], 1, 1)[0].forEach((v, c) =>
  nearly(v, [0.9, 0.9, 0.9, 0][c])); // No bright contribution from zero alpha.
for (const [width, height] of [[1, 1], [1, 13], [13, 1], [2, 2], [41, 17]]) {
  const pixels = impulse(width, height, 0, 0, [2, 1, 0.5, 1]);
  for (const scale of [0.25, 1, 2]) {
    const result = render(pixels, width, height, {radius: 8, threshold: 0, quality: 2}, scale);
    assert.ok(result.every(p => p.every(Number.isFinite)));
  }
}
const e = new WebAssembly.Instance(module_, {}).exports;
assert.notEqual(e.ec_render(1, 1, 1, 0, 13, 0, 1), 0, 'wrong param count rejected');
assert.notEqual(e.ec_render(1, 0, 1, 0, 14, 0, 1), 0, 'invalid dimensions rejected');
assert.notEqual(e.ec_render(1, 8192, 8192, 0, 14, 0, 1), 0, 'oversized frame rejected');
console.log('PASS: independent Deep Glow WASM ABI, real bloom frames, alpha, quality, threshold and controls');
