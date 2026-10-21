// AE host simulation for the opt-in, no-project observation script. It is NOT
// evidence that a particular installed AE or third-party effect will render.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');
const script = fs.readFileSync(path.join(__dirname, '..', 'tools',
  'collect_ae_effect_observations.jsx'), 'utf8');

function scenario({collision = false, busy = false, missingTemplate = false} = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ae-probe-mock-'));
  try {
    for (const name of ['chart_training_input.png', 'chart_check_input.png']) {
      fs.writeFileSync(path.join(dir, name), 'fake test-only input');
    }
    if (collision) fs.writeFileSync(path.join(dir, 'chart_training_ae.png'), 'USER FILE');
    class AEFile {
      constructor(filename) {this.fsName = filename; this.name = path.basename(filename);}
      get exists() {return fs.existsSync(this.fsName);}
      get length() {return this.exists ? fs.statSync(this.fsName).size : 0;}
      rename(name) {
        fs.renameSync(this.fsName, path.join(path.dirname(this.fsName), name));
        return true;
      }
      open(mode) {assert.equal(mode, 'w'); assert.equal(this.exists, false); return true;}
      write(data) {fs.writeFileSync(this.fsName, data, 'utf8');}
      close() {}
    }
    class AEFolder {
      constructor(filename) {this.fsName = filename;}
      getFiles() {return fs.readdirSync(this.fsName).map(n => new AEFile(path.join(this.fsName, n)));}
    }
    AEFolder.selectDialog = () => new AEFolder(dir);
    const effect = {
      name: 'Experimental beam', matchName: 'org.vendor.beam',
      propertyType: 2, numProperties: 1,
      property(index) {
        assert.equal(index, 1);
        return {name: 'Core', propertyType: 2, numProperties: 3,
          property(child) {
            if (child === 1) return {
              name: 'Radius', matchName: 'vendor.radius', propertyType: 1,
              propertyValueType: 1, hasMin: true, minValue: 0, hasMax: false,
              canVaryOverTime: true, canSetExpression: false, value: 3.25,
            };
            if (child === 2) return {
              name: 'Color', matchName: 'vendor.colour', propertyType: 1,
              propertyValueType: 4, value: [1, 0.2, 0.5, 1],
            };
            return {
              name: 'Curve', matchName: 'vendor.curve', propertyType: 1,
              propertyValueType: 5, get value() {throw Error('custom/private values must not be read');},
            };
          }};
      },
    };
    const selected = {displayName: 'Experimental beam', matchName: 'org.vendor.beam', version: '2.0'};
    const comps = [], footage = [], items = [], userItem = {render: busy, userWork: true};
    let renders = 0, starts = 0, ends = 0;
    const project = {
      bitsPerChannel: 16, workingSpace: 'sRGB', linearBlending: false,
      get file() {throw Error('original .aep must not be accessed');},
      get activeItem() {throw Error('user project content must not be accessed');},
      save() {throw Error('must not save the current project');},
      importFile(options) {
        const file = options.file;
        assert.ok(file.exists);
        const image = {
          width: file.name.includes('training') ? 852 : 256,
          height: file.name.includes('training') ? 840 : 192,
          remove() {this.removed = true;},
        };
        footage.push(image);
        return image;
      },
      items: {addComp(name, width, height, pixelAspect, duration, fps) {
        assert.match(name, /^ArtCraft probe/);
        assert.equal(pixelAspect, 1);
        assert.equal(duration, 1);
        assert.equal(fps, 30);
        const comp = {
          frameDuration: 1 / 30, width, height,
          layers: {add(img) {
            assert.equal(img.width, width);
            return {property(field) {
              assert.equal(field, 'ADBE Effect Parade');
              return {
                canAddProperty(match) {return match === selected.matchName;},
                addProperty(match) {assert.equal(match, selected.matchName); return effect;},
              };
            }};
          }},
          remove() {this.removed = true;},
        };
        comps.push(comp);
        return comp;
      }},
      renderQueue: {
        get numItems() {return (busy ? 1 : 0) + items.filter(x => !x.removed).length;},
        item(index) {return busy && index === 1 ? userItem : items[index - (busy ? 2 : 1)];},
        items: {add(comp) {
          const module = {
            templates: missingTemplate ? ['Lossless'] : ['PNG Sequence with Alpha'],
            applyTemplate(name) {assert.equal(name, 'PNG Sequence with Alpha');},
            file: null,
          };
          const item = {
            comp, render: true, status: 'QUEUED',
            outputModule(n) {assert.equal(n, 1); return module;},
            remove() {this.removed = true;},
          };
          items.push(item);
          return item;
        }},
        render() {
          renders++;
          assert.equal(busy, false, 'must never render queued user work');
          for (const item of items) {
            assert.equal(item.timeSpanStart, 0);
            assert.ok(Math.abs(item.timeSpanDuration - 1 / 30) < 1e-8);
            const output = item.outputModule(1).file;
            assert.ok(output.fsName.startsWith(dir));
            const numbered = output.name.replace('.png', '_00000.png');
            fs.writeFileSync(path.join(dir, numbered), 'simulated frame');
            item.status = 'DONE';
          }
        },
      },
    };
    const messages = [];
    const app = {
      project, effects: [selected], version: '25.1', buildNumber: 123,
      beginUndoGroup() {starts++;}, endUndoGroup() {ends++;},
      newProject() {throw Error('must not create/close/replace a project');},
    };
    const sandbox = {
      app, File: AEFile, Folder: AEFolder,
      ImportOptions: function (file) {this.file = file;},
      PropertyType: {PROPERTY: 1},
      PropertyValueType: {OneD: 1, TwoD: 2, ThreeD: 3, COLOR: 4,
        CUSTOM_VALUE: 5, SHAPE: 6, LAYER_INDEX: 7},
      RQItemStatus: {DONE: 'DONE'},
      prompt(message) {assert.match(message, /matchName/); return 'org.vendor.beam';},
      confirm(message) {assert.match(message, /NO \.aep/); return true;},
      alert(message) {messages.push(message);},
      JSON, isFinite, Math,
    };
    vm.runInNewContext(script, sandbox, {timeout: 4000});
    if (collision || busy || missingTemplate) {
      assert.equal(renders, 0);
      assert.equal(fs.existsSync(path.join(dir, 'ae_probe_profile.json')), false);
      assert.ok(messages.some(m => m.includes('stopped')), messages);
      if (collision) assert.equal(fs.readFileSync(path.join(dir, 'chart_training_ae.png'), 'utf8'), 'USER FILE');
    } else {
      assert.equal(renders, 1);
      const profile = JSON.parse(fs.readFileSync(path.join(dir, 'ae_probe_profile.json'), 'utf8'));
      const observation = JSON.parse(fs.readFileSync(path.join(dir, 'ae_probe_observation.json'), 'utf8'));
      if (process.argv[2]) fs.writeFileSync(process.argv[2], JSON.stringify(profile));
      assert.equal(profile.effect_match_name, selected.matchName);
      assert.equal(profile.properties[0].min_value, 0);
      assert.equal(profile.properties[0].max_value, null);
      assert.deepEqual(Array.from(profile.properties[0].groups), ['Core']);
      assert.equal(profile.properties[2].ui_control, 'unknown');
      assert.ok(!('value' in profile.properties[0]), 'value-free profile for --ae-profile');
      assert.equal(observation.effect.match_name, selected.matchName);
      assert.equal(observation.host.bits_per_channel, 16);
      assert.equal(observation.host.working_space, 'sRGB');
      assert.equal(observation.host.linear_blending, false);
      assert.equal(observation.new_instance_values.length, 2);
      assert.equal(observation.new_instance_values[0].value, 3.25);
      assert.deepEqual(observation.new_instance_values[1].value, [1, .2, .5, 1]);
      assert.equal(observation.samples.length, 2);
      assert.equal(fs.existsSync(path.join(dir, 'chart_training_ae.png')), true);
      assert.equal(fs.existsSync(path.join(dir, 'chart_check_ae.png')), true);
      assert.ok(messages.some(m => m.includes('Probe complete')));
      assert.ok(!JSON.stringify(observation).includes(dir), 'no current project/disk path in report');
      assert.equal(starts, 1);
      assert.equal(ends, 1);
    }
    assert.ok(items.every(item => item.removed), 'only temporary queue entries cleaned');
    assert.ok(comps.every(comp => comp.removed), 'only temporary comps cleaned');
    assert.ok(footage.every(image => image.removed), 'only temporary inputs cleaned');
    assert.equal(userItem.userWork, true);
    assert.equal(userItem.removed, undefined);
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
}
scenario();
scenario({collision: true});
scenario({busy: true});
scenario({missingTemplate: true});
console.log('PASS: local AE probe collects a fresh numeric inventory and frames without a project, '
  + 'and refuses queue/output collisions (host mock only)');
