/*
 * MBOM Copier - main: MBC.start(widget, {base, version}) is called by index.html once all
 * files are loaded. Builds the UI, loads the platform modules, finds this tenant's 3DSpace,
 * reads the security context, checks the local service and wires up the events.
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

  function on(btn, fn) {
    var go = function () { if (btn.getAttribute("aria-disabled") === "false") fn(); };
    btn.addEventListener("click", go);
    btn.addEventListener("keydown", function (ev) { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); go(); } });
  }

  function wireEvents(ui) {
    on(ui.go, function () { M.search(ui.q.value); });
    on(ui.dry, M.dryRun);
    on(ui.copy, M.copy);
    on(ui.gear, function () { if (ui.settings.style.display === "none") M.openSettings(); else M.closeSettings(); });
    ui.q.addEventListener("keydown", function (ev) { if (ev.key === "Enter" || ev.keyCode === 13) { ev.preventDefault(); M.search(ui.q.value); } });
    ui.results.addEventListener("click", function (ev) {
      var tr = ev.target.closest ? ev.target.closest("tr.pick") : null;
      if (tr && tr.getAttribute("data-id")) M.loadSource(tr.getAttribute("data-id"));
    });
    ui.settings.addEventListener("click", function (ev) {
      var b = ev.target.closest ? ev.target.closest("[data-act]") : null;
      if (b) M.settingsAction(b.getAttribute("data-act"));
    });
    // a changed option makes the last dry run stale
    function stale() {
      if (!M.plan || M.busy) return;
      M.plan = null;
      if (M.src) M.renderTable(M.previewRows(M.src));
      M.ui.summary.innerHTML = "";
      M.setStatus("Options changed: run the dry run again.");
      M.refreshButtons();
    }
    ui.reuse.addEventListener("change", stale);
    ui.suffix.addEventListener("input", stale);

    var w = M.w;
    if (w.addEvent) {
      w.addEvent("onRefresh", function () { M.checkService().catch(function () { /* shown in the bar */ }); });
      w.addEvent("endEdit", function () {
        var v = w.getValue("securityContext");
        if (v) { M.app.ctx = "ctx::" + v; ui.ctx.textContent = "Source: " + M.app.tenant + " · " + v; }
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
            if (obj.envId && M.app.tenant && String(obj.envId).toUpperCase() !== String(M.app.tenant).toUpperCase()) {
              return M.setStatus("That item is from " + obj.envId + "; this widget reads from " + M.app.tenant + ".", true);
            }
            ui.q.value = obj.displayName || obj.objectId;
            if (M.ready) M.loadSource(obj.objectId);
          } catch (badDrop) { M.setStatus("That drop didn't contain a 3DEXPERIENCE object.", true); }
        }
      });
    } catch (noDnD) { ui.drop.textContent = "(drag & drop unavailable here — use the search box)"; }
  }

  function startup(Compass, startupTimer) {
    M.app.tenant = M.w.getValue("x3dPlatformId");
    M.step("finding this tenant's 3DSpace service" + (M.app.tenant ? " (" + M.app.tenant + ")" : ""));
    Compass.getServiceUrl({
      serviceName: "3DSpace",
      platformId: M.app.tenant,
      onComplete: function (url) {
        M.app.space = (Array.isArray(url) ? url[0].url : url).replace(/\/$/, "");
        M.loadContext().then(function () {
          M.ready = true; clearTimeout(startupTimer);
          M.ui.ctx.textContent = "Source: " + M.app.tenant + " · " + M.app.ctx.replace(/^ctx::/, "");
          M.setStatus("Ready. Drop or search the top Manufacturing Item of the MBOM to copy.");
          M.refreshButtons();
          M.checkService().catch(function (e) {
            if (e.offline || e.status === 401) M.setStatus("Ready to preview. To copy, start the service on this PC and pair it in ⚙ Settings.");
          });
        }).catch(function (e) { clearTimeout(startupTimer); M.setStatus(e.message, true); });
      },
      onFailure: function () { clearTimeout(startupTimer); M.setStatus("No 3DSpace service found for this tenant.", true); }
    });
  }
})(window.MBC);
