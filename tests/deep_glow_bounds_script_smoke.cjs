// Simulated EffectCraft scripting object model, NOT a desktop UI integration test.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const script = fs.readFileSync(path.join(__dirname, '..', 'effectcraft_plugins',
  'ApplyDeepGlowWithBounds.jsx'), 'utf8');
const id = 'org.artcraft_converter.deep_glow';
const added = [];
const effects = {
  get numProperties() { return added.length; },
  property(k) { return added[k - 1] || null; },
  canAddProperty(name) { return name === id; },
  addProperty(name) {
    const fx = {
      matchName: name === 'ADBE Grow Bounds' ? 'ADBE Grow Bounds' : name,
      name: name === id ? 'Deep Glow (independent port)' : 'Grow Bounds',
      property(key) {
        if (key === 'Pixels') return this.pixels || (this.pixels = {expression: ''});
        if (key === 'Radius (px)') return {value: 48};
        throw Error(`Unexpected property: ${key}`);
      },
    };
    added.push(fx);
    return fx;
  },
};
const layer = {name: 'Footage', width: 120, height: 90, locked: false,
  adjustmentLayer: false,
  property(key) { assert.equal(key, 'ADBE Effect Parade'); return effects; }};
class CompItem {}
const comp = new CompItem();
comp.selectedLayers = [layer];
let messages = [], groups = [], pluginPresent = true;
const app = {
  project: {activeItem: comp},
  run(key) {
    assert.equal(key, 'effect.plugins.list');
    return {plugins: pluginPresent ? [{id}] : []};
  },
  beginUndoGroup(name) { groups.push(['begin', name]); },
  endUndoGroup() { groups.push(['end']); },
};
const context = {app, CompItem, alert: text => messages.push(text), isFinite, JSON, Math};
vm.runInNewContext(script, context, {timeout: 1000});
assert.deepEqual(added.map(e => e.matchName), ['ADBE Grow Bounds', id]);
assert.match(added[0].name, /Grow Bounds for Deep Glow/);
assert.match(added[1].name, /Deep Glow \+ Bounds/);
const expr = added[0].property('Pixels').expression;
assert.match(expr, /effect\("Deep Glow \+ Bounds 1"\)/);
function evaluate(radius) {
  return vm.runInNewContext(expr, {Math, effect: name => {
    assert.equal(name, added[1].name);
    return key => { assert.equal(key, 'Radius (px)'); return radius; };
  }});
}
assert.equal(evaluate(48), 112);
assert.equal(evaluate(128), 272);
assert.ok(evaluate(1e9) <= 4000);
assert.ok(groups.length === 2 && groups[1][0] === 'end');
assert.match(messages[0], /Added Grow Bounds > Deep Glow to 1 layer/);
// Running twice must not accidentally double the light.
vm.runInNewContext(script, context, {timeout: 1000});
assert.equal(added.length, 2);
assert.match(messages[1], /already exists/);
// The script refuses an impossible >9M-pixel frame before touching the stack.
added.length = 0;
layer.width = 4000; layer.height = 3000;
vm.runInNewContext(script, context, {timeout: 1000});
assert.equal(added.length, 0);
assert.match(messages[2], /within the pixel budget/);
// Missing WASM is reported without an orphan Grow Bounds effect.
layer.width = 120; layer.height = 90; pluginPresent = false;
vm.runInNewContext(script, context, {timeout: 1000});
assert.equal(added.length, 0);
assert.match(messages[3], /Load the Deep Glow/);
console.log('PASS: EffectCraft script mock links Grow Bounds to Radius before glow');
