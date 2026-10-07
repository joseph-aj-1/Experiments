/*
 * Route Viewer - main: RTV.start(widget, {base, version}) is called by index.html once all
 * files are loaded. Loads the platform modules, finds the 3DSpace and UsersGroup services,
 * reads the security context and wires up the events.
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
        M.WAFData = WAFData;
        wireEvents(ui);
        M.initFilters(ui);
        enableDrop(ui, DnD);
        startup(Compass, startupTimer);
      },
      function (err) {
        clearTimeout(startupTimer);
        M.setStatus("Could not load platform modules: " + ((err && err.requireModules) || err) + ". Is this running inside a 3DDashboard?", true);
      });
  };

  function reload() { var v = M.app.view; if (v) { M.clearGroupCache(); M.show(v.route.id); } }

  function wireEvents(ui) {
    ui.wrap.addEventListener("click", function (ev) {
      var t = ev.target;
      if (t === ui.go) return M.search(ui.q.value);
      if (t === ui.refresh) return ui.refresh.getAttribute("aria-disabled") === "false" && reload();
      var tr = t.closest ? t.closest("tr.pick") : null;
      if (tr && tr.getAttribute("data-id")) M.show(tr.getAttribute("data-id"));
    });
    ui.q.addEventListener("keydown", function (ev) { if (ev.key === "Enter" || ev.keyCode === 13) { ev.preventDefault(); M.search(ui.q.value); } });
    ui.go.addEventListener("keydown", function (ev) { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); M.search(ui.q.value); } });
    ui.refresh.addEventListener("keydown", function (ev) { if ((ev.key === "Enter" || ev.key === " ") && ui.refresh.getAttribute("aria-disabled") === "false") { ev.preventDefault(); reload(); } });
    var w = M.w;
    if (w.addEvent) {
      w.addEvent("onRefresh", reload);
      w.addEvent("endEdit", function () {
        var v = w.getValue("securityContext");
        if (v) { M.app.ctx = "ctx::" + v; ui.ctx.textContent = "Context: " + v; }
      });
    }
  }

  // A dropped Route opens directly; anything else (e.g. a Change Action) searches the
  // routes whose name/description mentions it (approval routes name their Change Action).
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
            if (!M.ready) return;
            if (/route/i.test(obj.objectType || "") && !/template/i.test(obj.objectType || "")) {
              ui.q.value = obj.displayName || obj.objectId;
              return M.show(obj.objectId);
            }
            ui.q.value = obj.displayName || obj.objectId;
            M.search(obj.displayName || obj.objectId, (obj.displayName || obj.objectId) + " (" + (obj.objectType || "object") + ")");
          } catch (badDrop) { M.setStatus("That drop didn't contain a 3DEXPERIENCE object.", true); }
        }
      });
    } catch (noDnD) { ui.drop.textContent = "(drag & drop unavailable here)"; }
  }

  function serviceUrl(Compass, name) {
    return new Promise(function (resolve) {
      try {
        Compass.getServiceUrl({
          serviceName: name, platformId: M.app.tenant,
          onComplete: function (u) { var v = Array.isArray(u) ? (u[0] && u[0].url) : u; resolve(v ? String(v).replace(/\/$/, "") : null); },
          onFailure: function () { resolve(null); }
        });
      } catch (noRegistry) { resolve(null); }
    });
  }

  function startup(Compass, startupTimer) {
    M.app.tenant = M.w.getValue("x3dPlatformId");
    M.step("finding this tenant's services" + (M.app.tenant ? " (" + M.app.tenant + ")" : ""));
    serviceUrl(Compass, "3DSpace").then(function (space) {
      if (!space) throw new Error("Could not find this tenant's 3DSpace service.");
      M.app.space = space;
      return serviceUrl(Compass, "usersgroup");
    }).then(function (ug) {
      // the registry names it "usersgroup"; else derive <tenant>-<region>-usersgroup. from 3DSpace
      M.app.usersgroup = ug || (/-space\./.test(M.app.space) ? M.app.space.replace("-space.", "-usersgroup.").replace(/\/enovia$/, "") : null);
      return M.loadContext();
    }).then(function () {
      M.ready = true; clearTimeout(startupTimer);
      M.ui.go.setAttribute("aria-disabled", "false");
      M.setStatus("Ready. Search for a route, or drop a Route or Change Action.");
    }).catch(function (e) { clearTimeout(startupTimer); M.setStatus(e.message, true); });
  }
})(window.RTV);
