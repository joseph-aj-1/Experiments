/*
 * Mfg Item Viewer - main: MFV.start(widget, {base, version}) is called by index.html once
 * all files are loaded. Builds the UI, loads the platform modules, finds the 3DSpace and
 * Sourcing services, reads the security context and wires up the events.
 */
(function (M) {
  "use strict";

  M.start = function (w, opts) {
    if (M.started) return;
    M.started = true;
    M.w = w;
    M.base = (opts && opts.base) || "";
    M.version = (opts && opts.version) || "dev";
    var ui = M.buildUi(w.body || document.body);

    // If start-up never finishes, say so instead of spinning forever.
    var startupTimer = setTimeout(function () {
      if (!M.ready) M.setStatus("Still starting after 20 s — last step: " + M.lastStep + ". Open the browser console (F12) for details.", true);
    }, 20000);

    M.step("loading platform modules");
    require(["DS/WAFData/WAFData", "DS/i3DXCompassServices/i3DXCompassServices", "DS/DataDragAndDrop/DataDragAndDrop"],
      function (WAFData, Compass, DnD) {
        M.WAFData = WAFData; M.Compass = Compass;
        wireEvents(ui);
        enableDrop(ui, DnD);
        startup(Compass, startupTimer);
      },
      function (err) {
        clearTimeout(startupTimer);
        M.setStatus("Could not load platform modules: " + ((err && err.requireModules) || err) + ". Is this running inside a 3DDashboard?", true);
      });
  };

  function wireEvents(ui) {
    ui.wrap.addEventListener("click", function (ev) {
      var t = ev.target;
      if (t === ui.go) return M.search(ui.q.value);
      if (t === ui.pdf) return ui.pdf.getAttribute("aria-disabled") === "false" && M.exportPdf();
      var sl = t.closest ? t.closest("a.spec") : null;
      if (sl) { ev.preventDefault(); ev.stopPropagation(); return M.openSpec(M.specIndex[sl.getAttribute("data-spec")], sl); }
      if (t.closest && t.closest(".dtoggle")) return M.toggleDetails();
      var tr = t.closest ? t.closest("tr.pick") : null;
      if (tr && tr.getAttribute("data-id")) M.show(tr.getAttribute("data-id"));
    });
    ui.details.addEventListener("keydown", function (ev) {
      if ((ev.key === "Enter" || ev.key === " ") && ev.target.classList && ev.target.classList.contains("dtoggle")) { ev.preventDefault(); M.toggleDetails(); }
    });
    ui.q.addEventListener("keydown", function (ev) { if (ev.key === "Enter" || ev.keyCode === 13) { ev.preventDefault(); M.search(ui.q.value); } });
    ui.pdf.addEventListener("keydown", function (ev) {
      if ((ev.key === "Enter" || ev.key === " ") && ui.pdf.getAttribute("aria-disabled") === "false") { ev.preventDefault(); M.exportPdf(); }
    });
    ui.go.addEventListener("keydown", function (ev) { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); M.search(ui.q.value); } });

    var w = M.w;
    if (w.addEvent) {
      w.addEvent("onRefresh", function () { if (ui.q.value) M.search(ui.q.value); });
      w.addEvent("endEdit", function () {
        var v = w.getValue("securityContext");
        if (v) { M.app.ctx = "ctx::" + v; ui.ctx.textContent = "Context: " + v; }
      });
    }
  }

  function enableDrop(ui, DnD) {
    try {
      DnD.droppable(ui.drop, {
        enter: function () { ui.drop.className = "drop over"; },
        leave: function () { ui.drop.className = "drop"; },
        drop: function (data) {
          ui.drop.className = "drop";
          try {
            var payload = typeof data === "string" ? JSON.parse(data) : data;
            var obj = payload.data.items[0];
            ui.q.value = obj.displayName || obj.objectId;
            if (M.ready) M.show(obj.objectId);
          } catch (badDrop) { M.setStatus("That drop didn't contain a 3DEXPERIENCE object.", true); }
        }
      });
    } catch (noDnD) { ui.drop.textContent = "(drag & drop unavailable here)"; }
  }

  function findSourcing(Compass) {
    // fallback derived from 3DSpace until/unless the service registry answers
    M.app.sourcing = /-space\./.test(M.app.space) ? M.app.space.replace("-space.", "-sourcing.") : null;
    try {
      Compass.getServiceUrl({
        serviceName: "Sourcing", platformId: M.app.tenant,
        onComplete: function (u) { var v = Array.isArray(u) ? (u[0] && u[0].url) : u; if (v) M.app.sourcing = String(v).replace(/\/$/, ""); },
        onFailure: function () {}
      });
    } catch (noRegistry) { /* keep the derived URL */ }
  }

  function startup(Compass, startupTimer) {
    M.app.tenant = M.w.getValue("x3dPlatformId");
    M.step("finding this tenant's 3DSpace service" + (M.app.tenant ? " (" + M.app.tenant + ")" : ""));
    Compass.getServiceUrl({
      serviceName: "3DSpace",
      platformId: M.app.tenant,
      onComplete: function (url) {
        M.app.space = (Array.isArray(url) ? url[0].url : url).replace(/\/$/, "");
        findSourcing(Compass);
        M.loadContext().then(function () {
          M.ready = true; clearTimeout(startupTimer);
          M.ui.go.setAttribute("aria-disabled", "false");
          M.setStatus("Ready. Search, or drop an item from MFN/search.");
        }).catch(function (e) { clearTimeout(startupTimer); M.setStatus(e.message, true); });
      },
      onFailure: function (e) { clearTimeout(startupTimer); M.setStatus("Could not find this tenant's 3DSpace service" + (e ? ": " + e : "") + ".", true); }
    });
  }

  // test hook: build the main report for a given view (used by test/run_test.py)
  window.__mfvPdfTest = function (JsPDF, view) { return M.buildPdf(JsPDF, view).doc.output("datauristring"); };
})(window.MFV);
