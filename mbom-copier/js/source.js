/*
 * MBOM Copier - source: find the dropped / searched Manufacturing Item in this tenant and
 * read its whole structure with the signed-in user's session (dsmfg, Details masks).
 * The raw items and instance lists are kept exactly as read: the local service turns them
 * into the copy plan with the same code as mbom_copy.py.
 *
 * M.src = { tenant, rootId, items: { id: item }, children: { id: [instance as read] } }
 */
(function (M) {
  "use strict";
  var esc = M.esc, MFG = "/resources/v1/modeler/dsmfg/dsmfg:MfgItem";
  var MAX_DEPTH = 25;

  function looksLikePhysicalId(s) { return /^[0-9A-F]{32}$/i.test(s); }
  function refIdOf(inst) { return (inst.referencedObject && inst.referencedObject.identifier) || inst.reference || ""; }

  M.search = function (text) {
    var ui = M.ui;
    if (!M.ready || M.busy) return;
    text = (text || "").trim();
    if (!text) return;
    ui.results.innerHTML = "";
    if (looksLikePhysicalId(text)) return M.loadSource(text.toUpperCase());
    M.setStatus("Searching…");
    M.get(MFG + "/search?$searchStr=" + encodeURIComponent(text) + "&$top=25")
      .then(function (resp) {
        var items = M.members(resp);
        if (!items.length) { M.setStatus("No Manufacturing Items match “" + text + "”. New items can take a minute to appear in search."); return; }
        var exact = items.filter(function (it) { return it.title === text || it.name === text; });
        if (exact.length === 1) return M.loadSource(exact[0].id);
        if (items.length === 1) return M.loadSource(items[0].id);
        M.setStatus(items.length + " matches — pick one.");
        ui.results.innerHTML = "<table class='pickt'><thead><tr><th>Title</th><th>Name</th><th>Type</th><th>Rev</th><th>State</th></tr></thead><tbody>" +
          items.map(function (it) {
            return "<tr class='pick' data-id='" + esc(it.id) + "'><td>" + esc(it.title) + "</td><td>" + esc(it.name) +
              "</td><td>" + esc(M.typeLabel(it.type)) + "</td><td>" + esc(it.revision) + "</td><td>" + esc(M.stateLabel(it.state)) + "</td></tr>";
          }).join("") + "</tbody></table>";
      })
      .catch(function (e) { M.setStatus(e.message, true); });
  };

  // read every distinct item and its instances once; resolves to M.src
  function readStructure(rootId, seq) {
    var items = {}, children = {}, itemP = {}, n = { items: 0 };
    function getItem(id) {
      if (!itemP[id]) {
        itemP[id] = M.get(MFG + "/" + encodeURIComponent(id) + "?$mask=dsmfg:MfgItemMask.Details").then(function (r) {
          var it = M.members(r)[0];
          if (!it) throw new Error("Manufacturing Item " + id + " was not found (or you can't see it in this context).");
          items[id] = it;
          n.items++;
          if (seq === M.loadSeq) M.setStatus("Reading the structure… " + n.items + " item" + (n.items === 1 ? "" : "s"));
          return it;
        });
      }
      return itemP[id];
    }
    function visit(id, path) {
      return getItem(id).then(function () {
        if (children[id]) return null;
        children[id] = [];                       // claimed: a shared item is expanded once
        return M.get(MFG + "/" + encodeURIComponent(id) + "/dsmfg:MfgItemInstance?$mask=dsmfg:MfgItemInstanceMask.Details")
          .then(M.members).then(function (insts) {
            children[id] = insts;
            return Promise.all(insts.map(function (inst) {
              var c = refIdOf(inst);
              if (!c) throw new Error("An instance under " + items[id].title + " has no reference.");
              if (path.indexOf(c) >= 0) throw new Error("The structure has a cycle at " + items[id].title + ".");
              if (path.length >= MAX_DEPTH) throw new Error("The structure is deeper than " + MAX_DEPTH + " levels.");
              return visit(c, path.concat(c));
            }));
          });
      });
    }
    return visit(rootId, [rootId]).then(function () {
      return { tenant: M.app.tenant, rootId: rootId, items: items, children: children };
    });
  }

  // depth-first rows for the table; a shared item is shown in full once, later as one "repeat" row
  M.previewRows = function (src) {
    var rows = [], seen = {};
    (function rec(id, level, inst) {
      var it = src.items[id] || {}, again = !!seen[id];
      rows.push({ level: level, id: id, title: it.title || "", name: it.name || "", type: it.type || "",
                  type_label: M.typeLabel(it.type), revision: it.revision || "", state: it.state || "",
                  instance: inst ? (inst.name || "") : "", quantity: inst ? M.qtyOf(inst.quantity) : "",
                  repeat: again, action: "" });
      if (again) return;
      seen[id] = true;
      (src.children[id] || []).forEach(function (k) { rec(refIdOf(k), level + 1, k); });
    })(src.rootId, 0, null);
    return rows;
  };
  // quantity as read ({value, unit}) or as planned ({inputValue, inputUnit})
  M.qtyOf = function (q) {
    if (!q || typeof q !== "object") return "";
    var v = q.inputValue != null ? q.inputValue : q.value, u = q.inputUnit || q.unit || "";
    if (v == null || v === "") return "";
    return String(+v === +v ? +v : v) + " " + String(u).toLowerCase().replace(/^meter$/, "m");
  };

  M.loadSource = function (id) {
    if (M.busy) return;
    var seq = ++M.loadSeq;
    M.ui.results.innerHTML = "";
    M.src = null; M.plan = null;
    M.renderTable(null);
    M.setStatus("Reading the structure…");
    return readStructure(id, seq).then(function (src) {
      if (seq !== M.loadSeq) return;
      M.src = src;
      var root = src.items[src.rootId];
      if (M.w.setTitle) M.w.setTitle("MBOM Copier: " + (root.title || root.name));
      var nItems = Object.keys(src.items).length;
      var nInst = Object.keys(src.children).reduce(function (s, k) { return s + src.children[k].length; }, 0);
      M.assocNote = [];
      M.renderTable(M.previewRows(src));
      M.loadAssoc(seq);
      M.setStatus(root.title + ": " + nItems + " item" + (nItems === 1 ? "" : "s") + ", " + nInst + " instance" + (nInst === 1 ? "" : "s") +
                  ". Next: Dry run.");
      M.refreshButtons();
    }).catch(function (e) { if (seq === M.loadSeq) { M.renderTable(null); M.setStatus(e.message, true); } });
  };
})(window.MBC);
