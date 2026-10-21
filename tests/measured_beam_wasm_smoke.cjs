// Exercise a converter-fitted generic line glow through the EffectCraft v1 ABI.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = process.argv[2];
assert.ok(path, 'pass a measured line-glow WASM');
const module_ = new WebAssembly.Module(fs.readFileSync(path));
assert.deepEqual(WebAssembly.Module.imports(module_), []);
const e = new WebAssembly.Instance(module_, {}).exports;
for (const name of ['ec_api_version', 'ec_manifest_ptr', 'ec_manifest_len',
                    'ec_alloc', 'ec_render', 'memory']) assert.ok(e[name], name);
assert.equal(e.ec_api_version(), 1);
const manifest = JSON.parse(Buffer.from(e.memory.buffer, e.ec_manifest_ptr(),
                                        e.ec_manifest_len()).toString('utf8'));
assert.equal(manifest.api, 1);
assert.deepEqual(manifest.params.map(p => p.id),
  ['start', 'end', 'core_radius', 'core_color', 'glow_size', 'intensity', 'mix']);
const w = 256, h = 192, nparams = 12, bytes = 8 * nparams + 16 * w * h;
const base = e.ec_alloc(bytes);
assert.ok(base > e.ec_manifest_ptr() + e.ec_manifest_len());
const pixels = base + nparams * 8;
const view = new DataView(e.memory.buffer);
const defaults = manifest.params;
const settings = [
  defaults[0].default[0] * w, defaults[0].default[1] * h,
  defaults[1].default[0] * w, defaults[1].default[1] * h,
  defaults[2].default, ...defaults[3].default,
  defaults[4].default, defaults[5].default, defaults[6].default,
];
assert.equal(settings.length, 12);
function render(mix, sx = settings[0]) {
  const params = settings.slice();
  params[0] = sx;
  params[2] = sx;
  params[11] = mix;
  params.forEach((v, i) => view.setFloat64(base + i * 8, v, true));
  // Independent checker of pixel input and transparency: a full replacement
  // must produce the same beam at Mix=100 without copying a stored frame.
  for (let i = 0; i < w * h; i++) {
    view.setFloat32(pixels + i * 16, .08, true);
    view.setFloat32(pixels + i * 16 + 4, .12, true);
    view.setFloat32(pixels + i * 16 + 8, .16, true);
    view.setFloat32(pixels + i * 16 + 12, .5, true);
  }
  assert.equal(e.ec_render(pixels, w, h, base, nparams, 0, 1), 0);
  function at(x, y) {
    return Array.from({length: 4}, (_, c) =>
      view.getFloat32(pixels + (y * w + x) * 16 + c * 4, true));
  }
  return {centre: at(w / 2, h / 2), side: at(10, h / 2), other: at(Math.round(w / 3), h / 2)};
}
const first = render(100);
assert.ok(first.centre[0] > .8 && first.centre[2] > .95, first.centre);
assert.ok(first.side[0] < .05 && first.side[2] < .25, first.side);
assert.equal(first.centre[3], 1);
const none = render(0);
for (const pixel of [none.centre, none.side]) {
  [0.08, 0.12, 0.16, 0.5].forEach((value, c) =>
    assert.ok(Math.abs(pixel[c] - value) < 1e-5, pixel));
}
const half = render(50);
assert.ok(Math.abs(half.centre[3] - .75) < 1e-5);
assert.ok(Math.abs(half.centre[0] - (.5 * .08 + .5 * first.centre[0])) < .01);
const moved = render(100, w / 3);
assert.ok(moved.other[0] > moved.centre[0] + .3,
          'point controls must actually move the rendered beam');
assert.notEqual(e.ec_render(pixels, 0, h, base, nparams, 0, 1), 0);
console.log('PASS: fitted procedural glow runs without imports; editable points, alpha, Mix');
