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
assert.equal(manifest.version, '0.4.0');
assert.equal(manifest.params.length, 14);
const rawManifest = Buffer.from(instance.memory.buffer, instance.ec_manifest_ptr(),
  instance.ec_manifest_len()).toString('utf8');
assert.match(rawManifest, /"default":48 +,/,
  'fixed-width manifest slots allow explicitly exported AE defaults');
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

// EffectCraft's Grow Bounds prepends a transparent border. With that host
// effect BEFORE the WASM, pixels beyond the original footage can receive light.
const pad = 12, sw = 5, sh = 5, aw = sw + 2 * pad, ah = sh + 2 * pad;
const padded = impulse(aw, ah, pad + sw - 1, pad + 2);
const bounded = render(padded, aw, ah, {radius: 16, exposure: 0, threshold: 50,
  threshold_smooth: 0, spread: 65, quality: 2});
for (const dx of [1, 2, 5]) {
  const outside = bounded[(pad + 2) * aw + pad + sw - 1 + dx];
  assert.ok(outside[0] > 0 && outside[3] > 0,
    `transparent region ${dx}px beyond footage must glow when the host pads it`);
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

// An isolated highlight must produce a smoothly fading, nearly circular halo.
// A single horizontal+vertical box blur has a flat square: it abruptly drops
// to zero on an axis while still glowing in the diagonal corner at that radius.
const haloSize = 81, haloCenter = 40;
const halo = render(impulse(haloSize, haloSize, haloCenter, haloCenter), haloSize, haloSize,
  {radius: 64, spread: 0, quality: 0, blend_mode: 2, exposure: 0,
   threshold: 50, threshold_smooth: 0, source_opacity: 0});
const at = (dx, dy) => halo[(haloCenter + dy) * haloSize + haloCenter + dx][0];
assert.ok(at(0, 0) > at(5, 0) && at(5, 0) > at(10, 0) && at(10, 0) > 0,
          'large-scale halo must fade gradually beyond the old square cutoff');
const axis = at(10, 0), diagonal = at(7, 7);
assert.ok(Math.abs(axis - diagonal) / Math.max(axis, diagonal) < 0.25,
          'points at comparable radial distances should receive comparable glow');
const totalGlow = halo.reduce((sum, pixel) => sum + pixel[0], 0);
nearly(totalGlow, 1, 0.001); // Unit impulse energy is conserved away from borders.

// The default mix of blur scales must not reintroduce the square outline.
const mixedSize = 129, mixedCenter = 64;
const mixed = render(impulse(mixedSize, mixedSize, mixedCenter, mixedCenter),
  mixedSize, mixedSize, {radius: 48, quality: 1, exposure: 0, blend_mode: 2,
                        threshold: 50, threshold_smooth: 0, source_opacity: 0});
const mixedAxis = mixed[mixedCenter * mixedSize + mixedCenter + 30][0];
const mixedDiagonal = mixed[(mixedCenter + 21) * mixedSize + mixedCenter + 21][0];
assert.ok(mixedAxis > 0 && mixedDiagonal > 0);
assert.ok(Math.abs(mixedAxis - mixedDiagonal) / Math.max(mixedAxis, mixedDiagonal) < 0.25,
          'default multi-scale halo must be approximately circular');

// Radius 256 is only the end of the convenient slider, NOT a hard effect
// limit: a typed value above it must actually broaden the rendered halo.
const wideSize = 97, wideCenter = 48;
const wideInput = impulse(wideSize, wideSize, wideCenter, wideCenter);
const wideControls = {spread: 0, quality: 0, blend_mode: 2, exposure: 0,
                      threshold: 50, threshold_smooth: 0, source_opacity: 0};
const narrowRadius = render(wideInput, wideSize, wideSize, {...wideControls, radius: 256});
const wideRadius = render(wideInput, wideSize, wideSize, {...wideControls, radius: 512});
const centerIndex = wideCenter * wideSize + wideCenter;
assert.ok(wideRadius[centerIndex][0] > 0 && wideRadius[centerIndex][0] < narrowRadius[centerIndex][0],
          'a radius beyond 256 must spread a highlight further');
const enormousRadius = render(wideInput, wideSize, wideSize, {...wideControls, radius: 1e9});
assert.deepEqual(enormousRadius, render(wideInput, wideSize, wideSize,
  {...wideControls, radius: wideSize * 16}), 'extreme input safely saturates at a frame-relative size');

const tinyHalo = render(impulse(21, 21, 10, 10), 21, 21,
  {radius: 8, spread: 0, quality: 0, blend_mode: 2, exposure: 0,
   threshold: 50, threshold_smooth: 0, source_opacity: 0});
const smallAt = x => tinyHalo[10 * 21 + 10 + x][0];
assert.ok(smallAt(0) > smallAt(1) && smallAt(1) > smallAt(2) && smallAt(2) > 0,
          'even a one-pixel scale must have a soft, non-square tail');

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
