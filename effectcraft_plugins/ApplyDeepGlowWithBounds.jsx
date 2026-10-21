// EffectCraft ONLY, File > Scripts > Run Script File...
// Load the matching Deep Glow (independent port) .wasm first, select footage
// layer(s) in a composition, then run. Do not run this in After Effects.
// EffectCraft WASM API v1 renders an in-place frame; the built-in Grow Bounds
// effect expands the layer before the glow and preserves its pixel offset.
// This is a workaround, not a change to the .wasm host ABI or AE's algorithm.
(function () {
  var id = "org.artcraft_converter.deep_glow";
  var registered = app.run("effect.plugins.list", {});
  var found = false;
  if (registered && registered.plugins) {
    for (var i = 0; i < registered.plugins.length; i++) {
      if (registered.plugins[i].id === id) found = true;
    }
  }
  if (!found) {
    alert("Load the Deep Glow (independent port) .wasm in EffectCraft first, then run this script again.");
    return;
  }
  var comp = app.project.activeItem;
  if (!(comp instanceof CompItem)) {
    alert("Open a composition and select footage layer(s) first.");
    return;
  }
  var selected = comp.selectedLayers;
  if (!selected.length) {
    alert("Select at least one footage layer first.");
    return;
  }
  var added = 0, warnings = [];
  // ec_render currently supports up to 9,000,000 input pixels. Leave a little
  // headroom for rounding; larger frames need a smaller source or a host fix.
  var maxPixels = 8950000;
  app.beginUndoGroup("Deep Glow with Grow Bounds");
  try {
    for (var i = 0; i < selected.length; i++) {
      var layer = selected[i];
      var effects = layer.property("ADBE Effect Parade");
      var w = layer.width, h = layer.height;
      if (layer.locked || layer.adjustmentLayer || !effects ||
          !effects.canAddProperty(id) || !isFinite(w) || !isFinite(h) ||
          w < 1 || h < 1 || w * h >= maxPixels) {
        warnings.push(layer.name + ": not an unlocked, supported footage/precomp layer within the pixel budget");
        continue;
      }
      var existing = false;
      for (var j = 1; j <= effects.numProperties; j++) {
        var fx = effects.property(j);
        if (fx.matchName === id && fx.name.indexOf("Deep Glow + Bounds ") === 0) existing = true;
      }
      if (existing) {
        warnings.push(layer.name + ": an auto-bounded glow already exists; not duplicated");
        continue;
      }
      // Solve (w + 2*p) * (h + 2*p) <= maxPixels. Both are effect-space
      // dimensions; preview scales and very large frames may still need care.
      var safe = Math.floor((Math.sqrt((w - h) * (w - h) + 4 * maxPixels) - w - h) / 4);
      var cap = Math.min(4000, Math.max(0, safe)); // Grow Bounds' host slider max.
      if (cap < 1) {
        warnings.push(layer.name + ": no room for a transparent border; use smaller footage/precomp");
        continue;
      }
      var suffix = 1, name;
      do {
        name = "Deep Glow + Bounds " + suffix++;
        var used = false;
        for (var j = 1; j <= effects.numProperties; j++) {
          if (effects.property(j).name === name) used = true;
        }
      } while (used);
      // The order is essential: padding BEFORE the in-place WASM glow.
      var grow = effects.addProperty("ADBE Grow Bounds");
      var glow = effects.addProperty(id);
      glow.name = name;
      grow.name = "Grow Bounds for " + name;
      // A conservative support estimate for the four-scale three-box blur.
      // Automatically follows changes/keyframes in Radius. Keep the effect's
      // name unchanged, or repair the expression after renaming the glow.
      grow.property("Pixels").expression = "Math.min(" + cap +
        ", Math.max(0, Math.ceil(2 * Math.max(0, effect(" +
        JSON.stringify(name) + ")(\"Radius (px)\")) + 16)))";
      var radius = Number(glow.property("Radius (px)").value);
      if (isFinite(radius) && 2 * radius + 16 > cap) {
        warnings.push(layer.name + ": current Radius needs more than " + cap +
          " px padding; this layer may still clip. Reduce its source size or use a comp-sized precomp.");
      }
      added++;
    }
  } finally {
    app.endUndoGroup();
  }
  alert("Added Grow Bounds > Deep Glow to " + added + " layer(s)." +
        (warnings.length ? "\n\nWarnings:\n" + warnings.join("\n") : "") +
        "\n\nKeep Grow Bounds BEFORE glow. For very large sources or radii the 9M-pixel WASM limit can still clip the halo.");
})();
