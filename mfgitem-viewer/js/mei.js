/*
 * Mfg Item Viewer - mei: Manufacturer Equivalent Items, found through Equivalent
 * Qualifications (Sourcing service, dssrc) and shown in the BOM table's MEI columns.
 */
(function (M) {
  "use strict";
  var esc = M.esc;
  var meiCache = {};

  function sourcingCsrf() {
    return M.request("GET", M.app.sourcing + "/resources/v1/application/CSRF", null, false).then(function (r) {
      var c = (r && r.csrf) || {};
      if (!c.value) throw new Error("No CSRF token from the Sourcing service.");
      return c;
    });
  }
  // POST contextLocate in batches of 20; resolves to { contextId: [qualification, ...] }
  function qualificationsFor(ids) {
    var byContext = {}, batches = [];
    for (var i = 0; i < ids.length; i += 20) batches.push(ids.slice(i, i + 20));
    return sourcingCsrf().then(function (csrf) {
      var hdr = {}; hdr[csrf.name || "ENO_CSRF_TOKEN"] = csrf.value;
      return Promise.all(batches.map(function (batch) {
        var body = { data: batch.map(function (id) {
          return { id: id, identifier: id, source: M.app.space, relativePath: "/resources/v1/modeler/dsmfg/dsmfg:MfgItem/" + id };
        }) };
        return M.request("POST", M.app.sourcing + "/resources/v1/modeler/dssrc/qualifications/contextLocate" +
                         "?type=equivalentQualification&$include=target,contexts", body, true, hdr)
          .then(function (resp) {
            var r = (resp && (resp.result || resp)) || {};
            (r.data || []).forEach(function (q) {
              (q.context || q.contexts || []).forEach(function (c) {
                var cid = c.id || c.identifier || String(c.relativePath || "").split("/").pop();
                (byContext[cid] = byContext[cid] || []).push(q);
              });
            });
          });
      }));
    }).then(function () { return byContext; });
  }
  // MEI details: dssrc record + engineering basics + manufacturer name (search with the Details mask)
  function meiDetails(id) {
    if (meiCache[id]) return meiCache[id];
    var out = { id: id };
    meiCache[id] = Promise.all([
      M.get("/resources/v1/modeler/dssrc/dssrc:ManufacturerEquivalentItems/" + encodeURIComponent(id))
        .then(function (r) { var m = M.members(r)[0] || {}; out.mpn = m.manufacturerPartNumber; out.partSource = m.partSource;
                             out.partSourceURL = m.partSourceURL; out.custom = m.IsCustomPart; }, function () {}),
      M.get("/resources/v1/modeler/dseng/dseng:EngItem/" + encodeURIComponent(id))
        .then(function (r) { var m = M.members(r)[0] || {}; out.title = m.title; out.name = m.name; out.revision = m.revision; out.state = m.state; }, function () {})
    ]).then(function () {
      var q = out.mpn || out.title || out.name;
      if (!q || q.length < 2) return out;
      return M.get("/resources/v1/modeler/dssrc/dssrc:ManufacturerEquivalentItems/search?$searchStr=" + encodeURIComponent(q) +
                   "&$mask=dsmvsrc:ManufacturerEquivalentItem.Details&$top=50")
        .then(function (r) {
          var hit = M.members(r).filter(function (m) { return m.id === id; })[0];
          if (hit) {
            out.manufacturer = hit.manufacturer; out.title = out.title || hit.title; out.name = out.name || hit.name;
            out.revision = out.revision || hit.revision; out.state = out.state || hit.state; out.mpn = out.mpn || hit.manufacturerPartNumber;
          }
          return out;
        }, function () { return out; });
    });
    return meiCache[id];
  }
  function meiSummary(html, isError) {
    var e = M.ui.details.querySelector(".meisum");
    if (e) { e.innerHTML = html; e.className = "sub meisum" + (isError ? " error" : ""); }
  }
  function setMeiCells(id, cells, none) {
    Array.prototype.forEach.call(M.ui.details.querySelectorAll("tr[data-mid='" + id + "']"), function (tr) {
      var cell = function (c) { return tr.querySelector(".mc-" + c); };
      if (!cell("mei")) return;
      cell("mei").innerHTML = cells.mei; cell("mfr").innerHTML = cells.mfr; cell("mpn").innerHTML = cells.mpn; cell("q").innerHTML = cells.q;
      tr.className = tr.className.replace(/\s*no-mei/, "") + (none ? " no-mei" : "");
    });
  }
  function targetId(q) { var t = q.target || {}; return t.id || t.identifier; }

  M.loadMei = function (item, bomRows, seq) {
    var ids = M.tableItemIds(item, bomRows), view = M.app.view;
    var clearAll = function (text) { ids.forEach(function (id) { setMeiCells(id, { mei: text, mfr: "", mpn: "", q: "" }, true); }); };
    if (!M.app.sourcing) {
      var msg = "Manufacturer Equivalent Items: Sourcing service not available on this tenant.";
      clearAll("—"); meiSummary(msg); if (view) view.meiText = msg;
      return;
    }
    var p = qualificationsFor(ids).then(function (byContext) {
      var meiIds = {};
      ids.forEach(function (id) { (byContext[id] || []).forEach(function (q) { var mid = targetId(q); if (mid) meiIds[mid] = true; }); });
      return Promise.all(Object.keys(meiIds).map(meiDetails)).then(function (list) {
        if (seq !== M.loadSeq) return;                   // user opened something else meanwhile
        var byId = {}; list.forEach(function (m) { byId[m.id] = m; });
        var withMei = 0;
        ids.forEach(function (id) {
          var qs = byContext[id] || [];
          if (view) view.mei[id] = qs.map(function (q) { return { q: q, m: byId[targetId(q)] || {} }; });
          if (!qs.length) return setMeiCells(id, { mei: "<span class='none'>No MEI</span>", mfr: "", mpn: "", q: "" }, true);
          withMei++;
          var lines = function (fn) { return qs.map(fn).join("<br/>"); };
          var m = function (q) { return byId[targetId(q)] || {}; };
          setMeiCells(id, {
            mei: lines(function (q) { var x = m(q);
                   return esc(x.title || "") + (x.name ? " <span class='note'>" + esc(x.name) + (x.revision ? " · " + esc(x.revision) : "") +
                          (x.state ? " · " + esc(M.stateLabel(x.state)) : "") + "</span>" : ""); }),
            mfr: lines(function (q) { return esc(m(q).manufacturer || ""); }),
            mpn: lines(function (q) { return esc(m(q).mpn || ""); }),
            q: lines(function (q) { return esc(q.title || q.name || "") + " <span class='note'>" + esc(q.state || "") +
                   (q.preferred === "TRUE" ? ", preferred" : "") + "</span>"; })
          }, false);
        });
        var summary = withMei + " of " + ids.length + " item" + (ids.length === 1 ? "" : "s") +
                      " have a Manufacturer Equivalent Item (via Equivalent Qualification)";
        meiSummary(summary);
        if (view) { view.meiText = summary; view.meiDone = true; }
      });
    }).catch(function (e) {
      if (seq !== M.loadSeq) return;
      clearAll("—");
      meiSummary("Could not load Manufacturer Equivalent Items: " + esc(e.message), true);
      if (view) { view.meiText = "Could not load Manufacturer Equivalent Items: " + e.message; view.meiError = true; }
    });
    if (view) view.meiPromise = p.then(function () {}, function () {});
  };
})(window.MFV);
