/*
 * Explicit opt-in settings SNAPSHOT for an installed Deep Glow 2 (PEDG) in AE.
 * Run in After Effects with ONE layer selected; choose its Deep Glow effect.
 * For factory defaults, add a FRESH effect before running. Otherwise values
 * can reflect keyframes/expressions at the current time, not factory defaults.
 * Only finite scalar parameter values, their names/match names and group names
 * are exported. No media, project path, frames, colours or arbitrary strings.
 * Review the JSON before sharing. Requires After Effects; not tested in AE here.
 */
(function () {
    if (typeof JSON === 'undefined' || typeof JSON.stringify !== 'function') {
        alert('This After Effects version cannot export JSON. Provide a parameter screenshot instead.');
        return;
    }
    var comp = app.project.activeItem;
    if (!(comp instanceof CompItem) || comp.selectedLayers.length !== 1) {
        alert('Select one layer with Deep Glow 2 in the active composition.');
        return;
    }
    var effects = comp.selectedLayers[0].property('ADBE Effect Parade');
    if (!effects || !effects.numProperties) {
        alert('The selected layer has no effects.');
        return;
    }
    var choices = [];
    for (var j = 1; j <= effects.numProperties; j++) {
        var e = effects.property(j);
        choices.push(j + ': ' + e.name + ' (' + e.matchName + ')');
    }
    var choice = effects.numProperties === 1 ? '1' : prompt(
        'Choose the installed Deep Glow effect:\n' + choices.join('\n'), '1');
    if (choice === null) return;
    var index = Number(choice);
    if (!isFinite(index) || index < 1 || index > effects.numProperties || Math.floor(index) !== index) {
        alert('Invalid effect number.');
        return;
    }
    var effect = effects.property(index);
    if (String(effect.matchName) !== 'PEDG') {
        alert('This is not the PiPL-identified Deep Glow effect (match name PEDG). Nothing exported.');
        return;
    }
    var properties = [];
    function walk(group, groups, depth) {
        if (depth > 16 || properties.length >= 512) return;
        for (var i = 1; i <= group.numProperties && properties.length < 512; i++) {
            var child;
            try { child = group.property(i); } catch (e) { continue; }
            if (!child) continue;
            if (child.propertyType !== PropertyType.PROPERTY) {
                var next = groups.slice(0);
                next.push(String(child.name));
                walk(child, next, depth + 1);
                continue;
            }
            // Do not copy opaque/custom values, path strings or colour/point arrays.
            try {
                if (child.propertyValueType !== PropertyValueType.OneD) continue;
                var v = child.value;
                if (typeof v !== 'number' || !isFinite(v)) continue;
                properties.push({
                    name: String(child.name), match_name: String(child.matchName),
                    groups: groups.slice(0), value_type: 'scalar', value: v
                });
            } catch (ignored) { /* Some effects do not expose every property. */ }
        }
    }
    walk(effect, [], 0);
    if (properties.length === 0) {
        alert('No readable numeric parameters were found; no file created.');
        return;
    }
    var snapshot = {
        format: 'artcraft.ae-effect-values', version: 1,
        effect_name: 'Deep Glow (PEDG)', effect_match_name: String(effect.matchName),
        properties: properties
    };
    var destination = File.saveDialog('Save Deep Glow numeric settings snapshot', '*.json');
    if (!destination) return;
    if (destination.exists) {
        alert('The destination already exists. Choose a new filename.');
        return;
    }
    destination.encoding = 'UTF-8';
    if (!destination.open('w')) {
        alert('Could not create the settings snapshot.');
        return;
    }
    try { destination.write(JSON.stringify(snapshot, null, 2)); }
    finally { destination.close(); }
    alert('Saved ' + properties.length + ' numeric parameter values. Review the JSON before sharing.');
})();
