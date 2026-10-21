// Offline ABI + pixel behavior tests in a real WebAssembly runtime (Node.js).
// Run: node tests/effectcraft_wasm_smoke.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const binary = fs.readFileSync(path.join(__dirname, '..', 'effectcraft_plugins', 'PixelSorter_EffectCraft.wasm'));
const module_ = new WebAssembly.Module(binary);
assert.deepEqual(WebAssembly.Module.imports(module_), [], 'EffectCraft plug-ins cannot import anything');
const first = new WebAssembly.Instance(module_, {}).exports;
const names = WebAssembly.Module.exports(module_).map(item => item.name);
for (const name of ['memory', 'ec_api_version', 'ec_manifest_ptr', 'ec_manifest_len', 'ec_alloc', 'ec_render']) {
  assert.ok(names.includes(name), `missing ${name}`);
}
assert.equal(first.ec_api_version(), 1);
const json = Buffer.from(first.memory.buffer, first.ec_manifest_ptr(), first.ec_manifest_len()).toString('utf8');
const manifest = JSON.parse(json);
assert.equal(manifest.api, 1);
assert.equal(manifest.params.length, 18);
const slot = Object.fromEntries(manifest.params.map((item, n) => [item.id, n]));

function render(pixels, width, height, overrides = {}, time = 0, scale = 1) {
  assert.equal(pixels.length, width * height);
  const e = new WebAssembly.Instance(module_, {}).exports;
  const p = manifest.params.map(item => Number(item.default ?? 0));
  for (const [key, value] of Object.entries(overrides)) {
    assert.ok(key in slot, `bad parameter ${key}`);
    p[slot[key]] = Number(value);
  }
  const base = e.ec_alloc(p.length * 8 + pixels.length * 16);
  assert.equal(base % 8, 0);
  assert.ok(base > e.ec_manifest_ptr() + e.ec_manifest_len());
  const pixelsAt = base + p.length * 8;
  let view = new DataView(e.memory.buffer);
  p.forEach((value, n) => view.setFloat64(base + n * 8, value, true));
  pixels.forEach((channels, n) => {
    assert.equal(channels.length, 4);
    channels.forEach((value, c) => view.setFloat32(pixelsAt + n * 16 + c * 4, value, true));
  });
  assert.equal(e.ec_render(pixelsAt, width, height, base, p.length, time, scale), 0);
  // memory.grow invalidates older JS ArrayBuffer views.
  view = new DataView(e.memory.buffer);
  return pixels.map((_, n) => Array.from({length: 4}, (_unused, c) =>
    view.getFloat32(pixelsAt + n * 16 + c * 4, true)));
}
function gray(values) {return values.map(v => [v, v, v, 1]);}
function nearly(actual, expected, tolerance = 1e-5) {
  assert.equal(actual.length, expected.length);
  actual.forEach((a, n) => assert.ok(Math.abs(a - expected[n]) <= tolerance,
    `at index ${n}: ${a} != ${expected[n]}`));
}
function grays(pixels) {return pixels.map(channels => channels[0]);}
const basic = [.8, .2, .6, .4];
nearly(grays(render(gray(basic), 4, 1, {threshold: 0})), [.2, .4, .6, .8]);
nearly(grays(render(gray(basic), 4, 1, {threshold: 0, invert: 1})), [.8, .6, .4, .2]);
nearly(grays(render(gray(basic), 4, 1, {threshold: 50})), basic);
nearly(grays(render(gray([.4, .2, .8, .6]), 4, 1,
                    {threshold: 50, affect: 1})), [.2, .4, .8, .6]);
nearly(grays(render(gray(basic), 1, 4, {angle: 90, threshold: 0})), [.2, .4, .6, .8]);
nearly(grays(render(gray(basic), 4, 1, {threshold: 0, length: 2})), [.2, .8, .4, .6]);
nearly(grays(render(gray(basic), 4, 1, {threshold: 0, offset: 1})), [.4, .6, .8, .2]);
nearly(grays(render(gray([.8,.6,.4,.2,.7,.5,.3,.1]), 4, 2,
                    {threshold: 0, block_size: 2})), [.1,.3,.5,.7,.2,.4,.6,.8]);
nearly(grays(render(gray(basic), 4, 1, {output: 1, threshold: 0})), [0, 1/3, 2/3, 1]);
nearly(grays(render(gray(basic), 4, 1, {output: 2, threshold: 50})), [1, 0, 1, 0]);
nearly(grays(render(gray(basic), 4, 1, {output: 3})), basic);
nearly(grays(render(gray(basic), 4, 1, {threshold: 0, blur: 1})), [.3,.4,.6,.7]);
nearly(grays(render(gray(basic), 4, 1, {threshold: 0,
                    feather_start: 1, feather_end: 1})), [.5,.4,.6,.6]);
nearly(grays(render(gray(basic), 4, 1, {threshold: 0, length: 4}, 0, .5)), [.2,.8,.4,.6]);
const [blue, red, green] = [[0,0,1,1], [1,0,0,1], [0,1,0,1]];
assert.deepEqual(render([blue, red, green], 3, 1,
                        {threshold: 0, sort_by: 9}), [red, green, blue]);
const highXor = [1,0,0,1], lowXor = [.6,.6,0,1], midXor = [.1,0,0,1];
nearly(render([highXor, lowXor, midXor], 3, 1,
              {threshold: 0, sort_by: 6}).map(px => px[0]), [.6,.1,1]);
const alpha = [[.9,.9,.9,1], [.2,.2,.2,.25]];
const preserve = render(alpha, 2, 1, {threshold: 0});
nearly(grays(preserve), [.8,.225]);
nearly(preserve.map(px => px[3]), [1,.25]);
const moved = render(alpha, 2, 1, {threshold: 0, preserve_alpha: 0});
nearly(grays(moved), [.2,.9]);
nearly(moved.map(px => px[3]), [.25,1]);
const jitter = {threshold: 0, offset_random: 2, cycle: 2, seed: 7};
assert.deepEqual(render(gray(basic), 4, 1, jitter, 2.5), render(gray(basic), 4, 1, jitter, 2.5));
const x = new WebAssembly.Instance(module_, {}).exports;
assert.equal(x.ec_render(1, 2, 3, 0, 17, 0, 1), 1, 'reject wrong flattened parameter count');

// Direction, grouping, shapes and scanline permutations: all in-range pixels
// remain present once when feather / blur / diagnostics are disabled.
let combinations = 0;
for (const width of [1, 2, 3, 8, 17, 64]) {
  for (const height of [1, 2, 4, 13, 31]) {
    const original = Array.from({length: width * height}, (_, n) => (n + 1) / (width * height + 1));
    const expected = original.map(Math.fround).sort((a,b) => a-b);
    for (const angle of [-270, -135, -89, -45, -5, 0, 5, 33, 45, 68, 89, 90, 135, 180, 270]) {
      for (const block_size of [1, 2, 5, 64]) {
        const result = render(gray(original), width, height, {threshold: 0, angle, block_size});
        assert.deepEqual(grays(result).sort((a,b) => a-b), expected);
        assert.ok(result.every(px => px[3] === 1));
        combinations++;
      }
    }
  }
}
console.log(`PASS: EffectCraft WASM ABI, sample frames, alpha, 18 controls, ${combinations} angle/shape/grouping permutations`);
