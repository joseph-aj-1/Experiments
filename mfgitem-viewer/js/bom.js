/*
 * Mfg Item Viewer - bom: search, item details and the multi-level BOM table
 * (Manufacturing Item Web Services, dsmfg). The MEI and Specification columns are
 * filled afterwards by mei.js and specs.js.
 */
(function (M) {
  "use strict";
  var esc = M.esc, MFG = "/resources/v1/modeler/dsmfg/dsmfg:MfgItem";
  var MAX_DEPTH = 15;          // safety stop for very deep structures
  var refCache = {};           // physical ID -> promise of item details (reused across the tree)

  function looksLikePhysicalId(s) { return /^[0-9A-F]{32}$/i.test(s); }

  M.search = function (text) {
    var ui = M.ui;
    if (!M.ready) return;
    text = (text || "").trim();
    if (!text) return;
    ui.details.innerHTML = ""; ui.results.innerHTML = "";
    M.app.view = null; ui.pdf.setAttribute("aria-disabled", "true");
    if (looksLikePhysicalId(text)) return M.show(text);
    M.setStatus("Searching…");
    M.get(MFG + "/search?$searchStr=" + encodeURIComponent(text) + "&$top=25")
      .then(function (resp) {
        var items = M.members(resp);
        if (!items.length) { M.setStatus("No Manufacturing Items match “" + text + "”. New items can take a minute to appear in search."); return; }
        if (items.length === 1) return M.show(items[0].id);
        M.setStatus(items.length + " matches — pick one.");
        ui.results.innerHTML = "<table><thead><tr><th>Title</th><th>Name</th><th>Type</th><th>Rev</th><th>State</th><th>Owner</th></tr></thead><tbody>" +
          items.map(function (it) {
            return "<tr class='pick' data-id='" + esc(it.id) + "'><td>" + esc(it.title) + "</td><td>" + esc(it.name) +
              "</td><td>" + esc(M.typeLabel(it.type)) + "</td><td>" + esc(it.revision) + "</td><td>" + esc(M.stateLabel(it.state)) +
              "</td><td>" + esc(it.owner) + "</td></tr>";
          }).join("") + "</tbody></table>";
      })
      .catch(function (e) { M.setStatus(e.message, true); });
  };

  function getItem(id) {
    if (!refCache[id]) {
      refCache[id] = M.get(MFG + "/" + encodeURIComponent(id)).then(M.members)
        .then(function (m) { return m[0] || null; }, function () { return null; });
    }
    return refCache[id];
  }
  function getInstances(id) {
    return M.get(MFG + "/" + encodeURIComponent(id) + "/dsmfg:MfgItemInstance?$mask=dsmfg:MfgItemInstanceMask.Details").then(M.members);
  }
  function refIdOf(inst) { return (inst.referencedObject && inst.referencedObject.identifier) || inst.reference || ""; }

  // Walk the whole structure below `id`; resolves to a flat, ordered list of
  // { level, inst, ref, refId, cycle, truncated } rows (depth-first, BOM order).
  function expand(id, level, ancestors, counter) {
    return getInstances(id).then(function (insts) {
      return Promise.all(insts.map(function (inst) {
        var refId = refIdOf(inst);
        return (refId ? getItem(refId) : Promise.resolve(null)).then(function (ref) {
          var row = { level: level, inst: inst, ref: ref || {}, refId: refId };
          counter.n++;
          M.setStatus("Expanding BOM… " + counter.n + " item" + (counter.n === 1 ? "" : "s") + " so far");
          if (!refId) return [row];
          if (ancestors.indexOf(refId) >= 0) { row.cycle = true; return [row]; }
          if (level >= MAX_DEPTH) { row.truncated = true; return [row]; }
          return expand(refId, level + 1, ancestors.concat(refId), counter)
            .then(function (sub) { return [row].concat(sub); }, function () { return [row]; });
        });
      })).then(function (lists) { return [].concat.apply([], lists); });
    });
  }

  M.show = function (id) {
    var seq = ++M.loadSeq;
    M.setStatus("Loading…");
    M.ui.results.innerHTML = "";
    refCache = {};
    var item;
    return M.get(MFG + "/" + encodeURIComponent(id) + "?$mask=dsmfg:MfgItemMask.Details")
      .then(function (res) {
        item = M.members(res)[0];
        if (!item) throw new Error("Manufacturing Item " + id + " was not found (or you can't see it in this context).");
        return expand(item.id, 1, [item.id], { n: 0 });
      }).then(function (rows) {
        if (seq !== M.loadSeq) return;
        render(item, rows);
        M.setStatus("");
        M.loadMei(item, rows, seq);
        M.loadSpecs(item, rows, seq);
      }).catch(function (e) { M.setStatus(e.message, true); });
  };

  function render(it, bomRows) {
    var ui = M.ui, collapsed = M.detailsCollapsed();
    var rows = [
      ["Name", it.name], ["Type", M.typeLabel(it.type)], ["Revision", it.revision], ["State", M.stateLabel(it.state)],
      ["Description", it.description || "—"], ["Owner", it.owner], ["Organization", it.organization],
      ["Collaborative space", it.collabspace], ["Created", it.created], ["Modified", it.modified],
      ["Planning required", M.yesNo(it.planningRequired)], ["Outsourced", M.yesNo(it.outsourced)],
      ["Target release date", it.targetReleaseDate || "—"], ["Locked by", it.reservedby || "—"],
      ["Physical ID", it.id]
    ];
    var kv = rows.map(function (r) { return "<dt>" + esc(r[0]) + "</dt><dd>" + esc(r[1]) + "</dd>"; }).join("");
    var depth = bomRows.reduce(function (d, r) { return Math.max(d, r.level); }, 0);
    var SPEC_COL = "<td class='spec-cell sc'>…</td>";
    var MEI_COLS = "<td class='mei-cell mc-mei'>…</td><td class='mei-cell mc-mfr'></td><td class='mei-cell mc-mpn'></td><td class='mei-cell mc-q'></td>";
    // Level 0 = the opened item itself (so its own MEI and specs show too), then the BOM
    var top = "<tr class='lvl0' data-mid='" + esc(it.id) + "'><td class='lvl'>0</td>" +
      "<td class='tree'>" + esc(it.title || "") + "</td><td></td><td>" + esc(it.name || "") + "</td>" +
      "<td>" + esc(M.typeLabel(it.type)) + "</td><td>" + esc(it.revision || "") + "</td><td>" + esc(M.stateLabel(it.state)) + "</td>" +
      SPEC_COL + MEI_COLS + "</tr>";
    var body = bomRows.map(function (r) {
      var ref = r.ref;
      var note = r.cycle ? " <span class='note'>(cycle — not expanded)</span>" :
                 r.truncated ? " <span class='note'>(deeper levels not shown)</span>" : "";
      return "<tr class='pick lvl" + Math.min(r.level, 9) + "' data-id='" + esc(r.refId) + "' data-mid='" + esc(r.refId) + "'>" +
        "<td class='lvl'>" + r.level + "</td>" +
        "<td class='tree' style='padding-left:" + (6 + r.level * 18) + "px'>" +
          "<span class='elbow'>└─</span>" + esc(ref.title || "") + note + "</td>" +
        "<td>" + esc(r.inst.name) + "</td><td>" + esc(ref.name || "") + "</td>" +
        "<td>" + esc(M.typeLabel(ref.type || (r.inst.referencedObject && r.inst.referencedObject.type))) + "</td>" +
        "<td>" + esc(ref.revision || "") + "</td><td>" + esc(M.stateLabel(ref.state)) + "</td>" +
        SPEC_COL + MEI_COLS + "</tr>";
    }).join("");
    var bom = "<div class='bomwrap'><table class='bom'><thead><tr><th>Level</th><th>Item</th><th>Instance</th><th>Name</th><th>Type</th><th>Rev</th><th>State</th>" +
      "<th class='sh'>Specification</th>" +
      "<th class='mh'>MEI</th><th class='mh'>Manufacturer</th><th class='mh'>Mfr part no.</th><th class='mh'>Qualification</th></tr></thead><tbody>" +
      top + body + "</tbody></table></div>" +
      (bomRows.length ? "" : "<p class='empty'>No BOM children.</p>");
    M.app.view = { item: it, rows: bomRows, kv: rows, depth: depth,
                   mei: {}, meiText: "Looking up Manufacturer Equivalent Items...", meiPromise: null,
                   specs: {}, specText: "Looking up Specification documents...", specPromise: null };
    ui.pdf.setAttribute("aria-disabled", "false");
    ui.details.innerHTML =
      "<div class='title dtoggle' role='button' tabindex='0' aria-expanded='" + (!collapsed) + "' title='Show or hide the item details'>" +
        esc(it.title) + " <span class='pill'>" + esc(M.typeLabel(it.type)) + "</span>" +
        "<span class='tg'>" + (collapsed ? "Show details ▸" : "Hide details ▾") + "</span></div>" +
      "<div class='dbody'" + (collapsed ? " style='display:none'" : "") + "><dl class='kv'>" + kv + "</dl></div>" +
      "<h3>BOM and Manufacturer Equivalent Items — " + bomRows.length + " BOM item" + (bomRows.length === 1 ? "" : "s") +
      (depth ? ", " + depth + " level" + (depth === 1 ? "" : "s") : "") + "</h3>" +
      "<div class='sub meisum'>Looking up Manufacturer Equivalent Items…</div>" +
      "<div class='sub specsum'>Looking up Specification documents…</div>" + bom;
    if (M.w.setTitle) M.w.setTitle("Mfg Item: " + (it.title || it.name));
  }

  // every distinct item in the table: the opened item first, then the BOM items
  M.tableItemIds = function (item, bomRows) {
    var ids = [item.id], seen = {};
    seen[item.id] = true;
    bomRows.forEach(function (r) { if (r.refId && !seen[r.refId]) { seen[r.refId] = true; ids.push(r.refId); } });
    return ids;
  };
})(window.MFV);
