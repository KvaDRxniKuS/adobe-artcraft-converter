/*
 * Local, opt-in BLACK-BOX OBSERVATION in a licensed, running After Effects.
 * File > Scripts > Run Script File...; no original .aep or plug-in DLL is read.
 * First prepare a folder containing chart_training_input.png and
 * chart_check_input.png using the converter's --prepare-reference command.
 *
 * Uses ONLY documented AE scripting APIs: app.effects, PropertyGroup,
 * ImportOptions, temporary comps/layers and the Render Queue. It neither
 * inspects code/memory of another plug-in nor calls a network service.
 * It does NOT disclose a renderer, UI widgets or a complete effect spec.
 * IMPORTANT: never launch this on unsaved work; if AE crashes, temporary
 * items may remain in the currently open project. It does NOT save a .aep.
 * AE desktop execution and the local PNG template still need real-world QA.
 */
(function () {
    var INPUTS = ['chart_training_input.png', 'chart_check_input.png'];
    var OUTPUTS = ['chart_training_ae.png', 'chart_check_ae.png'];
    var PROFILE = 'ae_probe_profile.json';
    var OBSERVATION = 'ae_probe_observation.json';
    var MAX_PROPERTIES = 512;
    var project = app.project;
    var temporary = [], queued = [], imported = [];
    var undoStarted = false;

    function sanitized(value, limit) {
        return String(value).replace(/[\u0000-\u001f\u007f]/g, ' ').substr(0, limit);
    }
    function guardedBoolean(object, field) {
        try { return typeof object[field] === 'boolean' ? object[field] : null; }
        catch (e) { return null; }
    }
    function guardedNumber(object, field) {
        try {
            var value = object[field];
            return typeof value === 'number' && isFinite(value) ? value : null;
        } catch (e) { return null; }
    }
    function guardedText(object, field) {
        try { return typeof object[field] === 'string' ? sanitized(object[field], 256) : null; }
        catch (e) { return null; }
    }
    function kind(prop) {
        try {
            var t = prop.propertyValueType;
            if (t === PropertyValueType.OneD) return 'scalar';
            if (t === PropertyValueType.TwoD || t === PropertyValueType.TwoD_SPATIAL) return 'point2';
            if (t === PropertyValueType.ThreeD || t === PropertyValueType.ThreeD_SPATIAL) return 'point3';
            if (t === PropertyValueType.COLOR) return 'color';
            if (t === PropertyValueType.CUSTOM_VALUE) return 'custom';
            if (t === PropertyValueType.SHAPE) return 'shape';
            if (t === PropertyValueType.TEXT_DOCUMENT) return 'text';
            if (t === PropertyValueType.LAYER_INDEX) return 'layer';
            if (t === PropertyValueType.MASK_INDEX) return 'mask';
        } catch (e) { /* Some third-party controls expose no scripting type. */ }
        return 'unknown';
    }
    function numericValue(prop, type) {
        // Only ordinary finite numbers on a NEW instance. Never serialize a
        // custom value, path, text, layer reference, expression or project item.
        if (type !== 'scalar' && type !== 'point2' && type !== 'point3' && type !== 'color') {
            return null;
        }
        try {
            var value = prop.value;
            if (type === 'scalar') {
                return typeof value === 'number' && isFinite(value) ? value : null;
            }
            var length = type === 'color' ? 4 : (type === 'point2' ? 2 : 3);
            if (!value || typeof value.length !== 'number' || value.length !== length) return null;
            var copy = [];
            for (var k = 0; k < length; k++) {
                if (typeof value[k] !== 'number' || !isFinite(value[k])) return null;
                copy.push(value[k]);
            }
            return copy;
        } catch (e) { return null; }
    }
    function inspect(effect) {
        var properties = [], values = [];
        function walk(group, parents, depth) {
            if (depth > 16 || properties.length >= MAX_PROPERTIES) return;
            for (var n = 1; n <= group.numProperties && properties.length < MAX_PROPERTIES; n++) {
                var child;
                try { child = group.property(n); } catch (e) { continue; }
                if (!child) continue;
                if (child.propertyType !== PropertyType.PROPERTY) {
                    var next = parents.slice(0);
                    next.push(sanitized(child.name, 128));
                    walk(child, next, depth + 1);
                    continue;
                }
                var type = kind(child);
                var hasMin = guardedBoolean(child, 'hasMin');
                var hasMax = guardedBoolean(child, 'hasMax');
                var record = {
                    name: sanitized(child.name, 256),
                    match_name: sanitized(child.matchName, 256),
                    groups: parents.slice(0),
                    value_type: type,
                    has_min: hasMin,
                    has_max: hasMax,
                    min_value: hasMin === true ? guardedNumber(child, 'minValue') : null,
                    max_value: hasMax === true ? guardedNumber(child, 'maxValue') : null,
                    can_vary_over_time: guardedBoolean(child, 'canVaryOverTime'),
                    can_set_expression: guardedBoolean(child, 'canSetExpression'),
                    ui_control: 'unknown'
                };
                properties.push(record);
                var value = numericValue(child, type);
                if (value !== null) {
                    values.push({name: record.name, match_name: record.match_name,
                                 groups: parents.slice(0), value_type: type, value: value});
                }
            }
        }
        walk(effect, [], 0);
        return {properties: properties, values: values};
    }
    function selectEffect() {
        var query = prompt('Type an installed effect name or matchName (e.g. Saber).\n'
                           + 'Only this effect will be probed, not the whole plug-in list.', '');
        if (query === null) return null;
        query = String(query).replace(/^\s+|\s+$/g, '').toLowerCase();
        if (!query) throw Error('Enter a nonempty installed effect name or matchName.');
        var matches = [], i, item, label;
        for (i = 0; i < app.effects.length; i++) {
            item = app.effects[i];
            label = String(item.displayName) + ' (' + String(item.matchName) + ')';
            if (label.toLowerCase().indexOf(query) !== -1) matches.push(item);
        }
        if (!matches.length) throw Error('No installed AE effect matches: ' + query);
        if (matches.length === 1) return matches[0];
        if (matches.length > 30) throw Error('Too many effects match. Enter a more specific matchName.');
        var choices = [];
        for (i = 0; i < matches.length; i++) {
            choices.push((i + 1) + ': ' + sanitized(matches[i].displayName, 90) +
                         ' (' + sanitized(matches[i].matchName, 90) + ')');
        }
        var choice = prompt('Choose ONE installed effect number:\n' + choices.join('\n'), '1');
        if (choice === null) return null;
        var index = Number(choice);
        if (!isFinite(index) || Math.floor(index) !== index || index < 1 || index > matches.length) {
            throw Error('Invalid effect number.');
        }
        return matches[index - 1];
    }
    function reference(folder, name) {
        return new File(folder.fsName + '/' + name);
    }
    function ensureEmptyOutputs(folder) {
        var exact = [PROFILE, OBSERVATION];
        var i, files = folder.getFiles();
        for (i = 0; i < exact.length; i++) {
            if (reference(folder, exact[i]).exists) throw Error(exact[i] + ' already exists; use a fresh folder.');
        }
        // AE may add frame numbers to a PNG Sequence. Never overwrite or
        // misidentify a pre-existing frame from a previous run.
        for (i = 0; i < files.length; i++) {
            var name = String(files[i].name);
            if (/^chart_(training|check)_ae(?:[._\[0-9]|$)/i.test(name)) {
                throw Error('An AE output already exists: ' + name + '; choose a fresh folder.');
            }
        }
    }
    function pngTemplate(module) {
        var options = module.templates;
        var basic = null, alpha = null;
        for (var i = 0; i < options.length; i++) {
            var name = String(options[i]);
            if (/^PNG Sequence with Alpha$/i.test(name)) alpha = name;
            if (/^PNG Sequence$/i.test(name)) basic = name;
        }
        // Prefer the RGB+alpha template if installed. AE template names are
        // user-configurable: fail rather than silently exporting a movie/JPEG.
        var selected = alpha || basic;
        if (!selected) throw Error('No PNG Sequence output-module template exists in this AE installation. '
                                   + 'Create it in AE or export PNG frames manually.');
        module.applyTemplate(selected);
        return selected;
    }
    function renderedFile(folder, stem) {
        var target = reference(folder, stem + '.png');
        if (target.exists && target.length > 0) return target;
        var entries = folder.getFiles(), found = [], pattern = new RegExp('^' + stem +
                                '(?:[._-]?(?:[0-9]+|\\[[0-9]+\\]))?\\.png$', 'i');
        for (var i = 0; i < entries.length; i++) {
            if (pattern.test(String(entries[i].name)) && entries[i].length > 0) found.push(entries[i]);
        }
        if (found.length !== 1 || target.exists) {
            throw Error('Expected ONE rendered PNG for ' + stem + '. Review the render output manually; '
                        + 'nothing will be overwritten.');
        }
        if (!found[0].rename(target.name) || !target.exists) {
            throw Error('Could not rename the single rendered frame to ' + target.name);
        }
        return target;
    }
    function writeNew(file, data) {
        if (file.exists) throw Error(file.name + ' already exists; nothing overwritten.');
        file.encoding = 'UTF-8';
        if (!file.open('w')) throw Error('Cannot create ' + file.name);
        try { file.write(JSON.stringify(data, null, 2)); }
        finally { file.close(); }
    }
    try {
        if (!project || typeof JSON === 'undefined' || typeof JSON.stringify !== 'function') {
            throw Error('This AE version cannot write the local observation JSON.');
        }
        var installed = selectEffect();
        if (!installed) return;
        var folder = Folder.selectDialog('Choose a local folder with the two prepared chart_*_input.png files');
        if (!folder) return;
        for (var i = 0; i < INPUTS.length; i++) {
            if (!reference(folder, INPUTS[i]).exists) throw Error('Missing ' + INPUTS[i]);
        }
        ensureEmptyOutputs(folder);
        var renderQueue = project.renderQueue;
        for (i = 1; i <= renderQueue.numItems; i++) {
            if (renderQueue.item(i).render === true) {
                throw Error('The render queue already contains queued user work. Finish or unqueue it first.');
            }
        }
        if (!confirm('Probe ' + installed.displayName + ' locally? Two temporary comps and queue items '
                     + 'will be created then removed. Two PNG frames, a value-free profile and a '
                     + 'separate numeric observation will be saved in the selected folder. '
                     + 'NO .aep is saved or uploaded. Save your open AE project first.')) return;
        app.beginUndoGroup('Local effect observation (temporary)');
        undoStarted = true;
        var inventory = null, templates = [], sizes = [];
        for (i = 0; i < INPUTS.length; i++) {
            var footage = project.importFile(new ImportOptions(reference(folder, INPUTS[i])));
            imported.push(footage);
            if (!footage || typeof footage.width !== 'number' ||
                    typeof footage.height !== 'number' ||
                    footage.width < 1 || footage.height < 1 ||
                    footage.width > 4096 || footage.height > 4096) {
                throw Error('Cannot probe this PNG size safely: ' + INPUTS[i]);
            }
            var comp = project.items.addComp('ArtCraft probe (temporary ' + i + ')',
                                             footage.width, footage.height, 1, 1, 30);
            temporary.push(comp);
            comp.resolutionFactor = [1, 1];
            var layer = comp.layers.add(footage);
            var effects = layer.property('ADBE Effect Parade');
            if (!effects || !effects.canAddProperty(String(installed.matchName))) {
                throw Error('This effect cannot be applied to the probe layer: ' + installed.matchName);
            }
            var effect = effects.addProperty(String(installed.matchName));
            if (i === 0) inventory = inspect(effect); // Fresh instance, not factory-guaranteed defaults.
            var item = renderQueue.items.add(comp);
            queued.push(item);
            item.timeSpanStart = 0;
            item.timeSpanDuration = comp.frameDuration;
            var outputModule = item.outputModule(1);
            var template = pngTemplate(outputModule);
            templates.push(template);
            outputModule.file = reference(folder, OUTPUTS[i]);
            sizes.push([footage.width, footage.height]);
        }
        renderQueue.render(); // Synchronous. Previous QUEUED items were explicitly prohibited.
        var results = [];
        for (i = 0; i < OUTPUTS.length; i++) {
            if (queued[i].status !== RQItemStatus.DONE) {
                throw Error('AE did not finish rendering ' + OUTPUTS[i] + '. Partial files were not deleted.');
            }
            var outputName = OUTPUTS[i].replace(/\.png$/, '');
            var rendered = renderedFile(folder, outputName);
            results.push({input: INPUTS[i], output: rendered.name, size: sizes[i], time_seconds: 0,
                          output_template: templates[i]});
        }
        var name = sanitized(installed.displayName, 256);
        var match = sanitized(installed.matchName, 256);
        var profile = {format: 'artcraft.ae-parameter-profile', version: 1,
                       effect_name: name, effect_match_name: match,
                       properties: inventory.properties};
        var observation = {
            format: 'artcraft.ae-black-box-observation', version: 1,
            effect: {display_name: name, match_name: match,
                     installed_version: sanitized(installed.version, 128)},
            host: {ae_version: sanitized(app.version, 128),
                   build_number: guardedNumber(app, 'buildNumber'),
                   bits_per_channel: guardedNumber(project, 'bitsPerChannel'),
                   working_space: guardedText(project, 'workingSpace'),
                   linear_blending: guardedBoolean(project, 'linearBlending')},
            new_instance_values: inventory.values,
            experiment: {composition_fps: 30, pixel_aspect: 1,
                         resolution_factor: [1, 1], effects_in_stack: [match],
                         fresh_effect_instance: true},
            samples: results,
            limitations: 'Only two opaque input charts, one fresh preset and time=0. No original project, source code, proprietary UI, masks, time dynamics or full behaviour was observed.'
        };
        // Do not overwrite an existing report if the user created one during rendering.
        if (reference(folder, PROFILE).exists || reference(folder, OBSERVATION).exists) {
            throw Error('A destination JSON was created during rendering; no JSON was overwritten.');
        }
        writeNew(reference(folder, PROFILE), profile);
        writeNew(reference(folder, OBSERVATION), observation);
        alert('Probe complete. Review ' + PROFILE + ', ' + OBSERVATION + ' and the two PNGs before sharing. '
              + 'No original AE project was saved or exported.');
    } catch (error) {
        alert('Local AE observation stopped: ' + error + '\nOnly temporary probe objects will be removed. '
              + 'Any partially rendered PNGs stay in the chosen folder for review.');
    } finally {
        // Never touch any existing user comp, layer, queue item or output.
        var cleanupErrors = [];
        for (var q = queued.length - 1; q >= 0; q--) {
            try { queued[q].remove(); } catch (queueError) { cleanupErrors.push('queue: ' + queueError); }
        }
        for (var c = temporary.length - 1; c >= 0; c--) {
            try { temporary[c].remove(); } catch (compError) { cleanupErrors.push('comp: ' + compError); }
        }
        for (var f = imported.length - 1; f >= 0; f--) {
            try { imported[f].remove(); } catch (fileError) { cleanupErrors.push('footage: ' + fileError); }
        }
        if (undoStarted) {
            try { app.endUndoGroup(); } catch (undoError) { cleanupErrors.push('undo: ' + undoError); }
        }
        if (cleanupErrors.length) {
            alert('Temporary AE probe items may remain in the currently open project. '
                  + 'Inspect them before saving: ' + cleanupErrors.join('; '));
        }
    }
})();
