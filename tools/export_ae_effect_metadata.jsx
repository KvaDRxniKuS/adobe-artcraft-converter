/*
 * Run this script INSIDE Adobe After Effects with a composition open and a layer
 * containing the effect selected (File > Scripts > Run Script File...). It reads
 * AE's public property metadata only. It never reads parameter VALUES, media,
 * footage or project paths, and it never executes an external DLL itself.
 *
 * AE scripting exposes group hierarchy, match names, min/max flags and
 * keyframe/expression capability. It does NOT reliably expose whether the UI
 * has a slider, a proprietary curve editor, or which blur/render algorithm the
 * effect uses. Those fields remain "unknown" in the JSON by design.
 *
 * This script cannot be smoke-tested without an installed After Effects host.
 */
(function () {
    function guardedBool(object, field) {
        try { return typeof object[field] === 'boolean' ? object[field] : null; }
        catch (e) { return null; }
    }
    function guardedNumber(object, field) {
        try {
            var value = object[field];
            return typeof value === 'number' && isFinite(value) ? value : null;
        } catch (e) { return null; }
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
        } catch (e) { /* The host may not expose this type. */ }
        return 'unknown';
    }
    var comp = app.project.activeItem;
    if (!(comp instanceof CompItem) || comp.selectedLayers.length !== 1) {
        alert('Select one layer with an AE effect in an active composition first.');
        return;
    }
    var effects = comp.selectedLayers[0].property('ADBE Effect Parade');
    if (!effects || effects.numProperties === 0) {
        alert('The selected layer has no effects.');
        return;
    }
    var names = [];
    for (var j = 1; j <= effects.numProperties; j++) {
        names.push(j + ': ' + effects.property(j).name);
    }
    var choice = effects.numProperties === 1 ? '1' : prompt(
        'Choose an effect number to export:\n' + names.join('\n'), '1');
    if (choice === null) return;
    var index = Number(choice);
    if (!isFinite(index) || index < 1 || index > effects.numProperties || Math.floor(index) !== index) {
        alert('Invalid effect number.');
        return;
    }
    var effect = effects.property(index);
    var properties = [];
    function walk(group, groups, depth) {
        if (depth > 16 || properties.length >= 512) return;
        for (var i = 1; i <= group.numProperties && properties.length < 512; i++) {
            var child;
            try { child = group.property(i); } catch (e) { continue; }
            if (!child) continue;
            if (child.propertyType !== PropertyType.PROPERTY) {
                var nextGroups = groups.slice(0);
                nextGroups.push(String(child.name));
                walk(child, nextGroups, depth + 1);
                continue;
            }
            var hasMin = guardedBool(child, 'hasMin');
            var hasMax = guardedBool(child, 'hasMax');
            properties.push({
                name: String(child.name),
                match_name: String(child.matchName),
                groups: groups.slice(0),
                value_type: kind(child),
                has_min: hasMin,
                has_max: hasMax,
                min_value: hasMin === true ? guardedNumber(child, 'minValue') : null,
                max_value: hasMax === true ? guardedNumber(child, 'maxValue') : null,
                can_vary_over_time: guardedBool(child, 'canVaryOverTime'),
                can_set_expression: guardedBool(child, 'canSetExpression'),
                ui_control: 'unknown'
            });
        }
    }
    walk(effect, [], 0);
    var profile = {
        format: 'artcraft.ae-parameter-profile',
        version: 1,
        effect_name: String(effect.name),
        effect_match_name: String(effect.matchName),
        properties: properties
    };
    if (typeof JSON === 'undefined' || typeof JSON.stringify !== 'function') {
        alert('This AE version does not expose JSON.stringify. Send a screenshot of Effect Controls instead.');
        return;
    }
    var destination = File.saveDialog('Save the AE effect metadata (no parameter values)', '*.json');
    if (!destination) return;
    if (destination.exists) {
        alert('The destination exists. Choose a new name so it is not overwritten.');
        return;
    }
    destination.encoding = 'UTF-8';
    if (!destination.open('w')) {
        alert('Could not create the metadata file.');
        return;
    }
    try { destination.write(JSON.stringify(profile, null, 2)); }
    finally { destination.close(); }
    alert('Saved ' + properties.length + ' property records. Review the JSON before sharing it.');
})();
