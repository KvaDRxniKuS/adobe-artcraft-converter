// Simulated AE scripting API contract for the optional, value-free JSX export.
// This does NOT replace testing inside an installed After Effects host.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, '..', 'tools',
  'export_ae_effect_metadata.jsx'), 'utf8');
class CompItem {}
const comp = new CompItem();
const numeric = {
  name: 'Radius', matchName: 'vendor.radius', propertyType: 1,
  propertyValueType: 2, hasMin: true, minValue: 0,
  hasMax: false, canVaryOverTime: true, canSetExpression: false,
  get value() { throw new Error('a parameter value must never be read'); },
};
const group = {
  name: 'Glow', propertyType: 2, numProperties: 1,
  property(index) { assert.equal(index, 1); return numeric; },
};
const effect = {
  name: 'Novel Glow', matchName: 'vendor.novel', propertyType: 2,
  numProperties: 1,
  property(index) { assert.equal(index, 1); return group; },
};
const effects = {
  numProperties: 1,
  property(index) { assert.equal(index, 1); return effect; },
};
comp.selectedLayers = [{property(name) {
  assert.equal(name, 'ADBE Effect Parade');
  return effects;
}}];
let saved = '', closed = false;
const output = {
  exists: false,
  open(mode) { assert.equal(mode, 'w'); return true; },
  write(data) { saved += data; },
  close() { closed = true; },
};
const context = {
  app: {project: {activeItem: comp}}, CompItem,
  PropertyType: {PROPERTY: 1}, PropertyValueType: {OneD: 2},
  File: {saveDialog(title, filter) {
    assert.match(title, /metadata/);
    assert.equal(filter, '*.json');
    return output;
  }},
  alert(message) { assert.match(message, /Saved 1 property/); },
  JSON, isFinite,
};
vm.runInNewContext(script, context, {timeout: 1000});
assert.equal(closed, true);
const inventory = JSON.parse(saved);
assert.equal(inventory.format, 'artcraft.ae-parameter-profile');
assert.equal(inventory.version, 1);
assert.equal(inventory.effect_name, 'Novel Glow');
assert.equal(inventory.effect_match_name, 'vendor.novel');
assert.equal(inventory.properties.length, 1);
assert.deepEqual(Array.from(inventory.properties[0].groups), ['Glow']);
assert.equal(inventory.properties[0].has_min, true);
assert.equal(inventory.properties[0].min_value, 0);
assert.equal(inventory.properties[0].has_max, false);
assert.equal(inventory.properties[0].max_value, null);
assert.equal(inventory.properties[0].can_vary_over_time, true);
assert.equal(inventory.properties[0].ui_control, 'unknown');
assert.ok(!('value' in inventory.properties[0]));
console.log('PASS: simulated AE metadata JSX exports groups and bounds without parameter values');
