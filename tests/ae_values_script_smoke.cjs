// Simulated AE host API for the opt-in Deep Glow numeric snapshot exporter.
// Does NOT verify integration with installed After Effects or factory defaults.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const script = fs.readFileSync(path.join(__dirname, '..', 'tools',
  'export_ae_deep_glow_values.jsx'), 'utf8');
class CompItem {}
const comp = new CompItem();
let secretAccessed = false;
const number = {name: 'Radius', matchName: 'PEDG-0001', propertyType: 1,
  propertyValueType: 2, value: 123};
const opaque = {name: 'Private string', matchName: 'PEDG-private', propertyType: 1,
  propertyValueType: 3, get value() { secretAccessed = true; return 'C:/private.aep'; }};
const group = {name: 'Glow', propertyType: 2, numProperties: 2,
  property(index) { return [number, opaque][index - 1]; }};
const effect = {name: 'private/project-name.aep', matchName: 'PEDG', numProperties: 1,
  property(index) { assert.equal(index, 1); return group; }};
comp.selectedLayers = [{property(name) {
  assert.equal(name, 'ADBE Effect Parade');
  return {numProperties: 1, property(index) { assert.equal(index, 1); return effect; }};
}}];
let saved = '', closed = false;
const target = {exists: false, encoding: '', open(mode) { return mode === 'w'; },
  write(text) { saved += text; }, close() { closed = true; }};
let messages = [];
const context = {app: {project: {activeItem: comp}}, CompItem,
  PropertyType: {PROPERTY: 1}, PropertyValueType: {OneD: 2},
  File: {saveDialog(title, filter) {
    assert.match(title, /Deep Glow numeric settings/);
    assert.equal(filter, '*.json');
    return target;
  }},
  JSON, isFinite, alert: text => messages.push(text)};
vm.runInNewContext(script, context, {timeout: 1000});
assert.equal(closed, true);
assert.equal(secretAccessed, false);
const snapshot = JSON.parse(saved);
assert.equal(snapshot.format, 'artcraft.ae-effect-values');
assert.equal(snapshot.version, 1);
assert.equal(snapshot.effect_match_name, 'PEDG');
assert.equal(snapshot.effect_name, 'Deep Glow (PEDG)');
assert.ok(!saved.includes('private/project-name.aep'));
assert.equal(snapshot.properties.length, 1);
assert.equal(snapshot.properties[0].value, 123);
assert.deepEqual(Array.from(snapshot.properties[0].groups), ['Glow']);
assert.ok(!saved.includes('private.aep'));
assert.match(messages.join(' '), /Saved 1 numeric/);
// A different effect must not produce a faux Deep Glow snapshot.
effect.matchName = 'another.plugin';
closed = false; saved = '';
vm.runInNewContext(script, context, {timeout: 1000});
assert.equal(closed, false);
assert.equal(saved, '');
assert.match(messages.join(' '), /not the PiPL-identified Deep Glow/);
console.log('PASS: AE mock exports only opted-in PEDG scalar values');
