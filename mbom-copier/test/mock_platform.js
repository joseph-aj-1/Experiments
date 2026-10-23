// Stand-in for the 3DDashboard runtime (source tenant). window.__SRC = { tenant, items: {id: item}, inst: {id: [instance]} }
// is injected by run_test.py from the same data the Python tests use.
(function () {
  var D = window.__SRC, SPACE = "https://" + D.tenant.toLowerCase() + "-eu1-demo-space.3dexperience.3ds.com/enovia";
  window.__calls = [];
  function respond(url, opts) {
    var u = new URL(url), p = u.pathname.replace("/enovia", ""), m;
    window.__calls.push({ method: opts.method, path: p, ctx: (opts.headers || {}).SecurityContext || null });
    if (u.searchParams.get("tenant") !== D.tenant) return [403, { message: "tenant missing" }];
    if (opts.method !== "GET") return [405, { message: "the widget must not write to the source" }];
    if (p === "/resources/modeler/pno/person")
      return [200, { collabspaces: [{ name: "Common Space", couples: [{ organization: { name: "Company Name" }, role: { name: "VPLMProjectLeader" } }] }],
                     preferredcredentials: { collabspace: { name: "Common Space" }, role: { name: "VPLMProjectLeader" }, organization: { name: "Company Name" } } }];
    if (!(opts.headers || {}).SecurityContext) return [401, { message: "SecurityContext required" }];
    if (p === "/resources/v1/modeler/dsmfg/dsmfg:MfgItem/search") {
      var q = (u.searchParams.get("$searchStr") || "").toLowerCase();
      return [200, { result: { member: Object.keys(D.items).map(function (k) { return D.items[k]; })
        .filter(function (i) { return (i.title + " " + i.name).toLowerCase().indexOf(q) >= 0; }) } }];
    }
    if ((m = p.match(/^\/resources\/v1\/modeler\/dsmfg\/dsmfg:MfgItem\/(\w+)\/dsmfg:MfgItemInstance$/))) {
      if (u.searchParams.get("$mask") !== "dsmfg:MfgItemInstanceMask.Details") return [400, { message: "Details mask expected" }];
      return [200, { result: { member: D.inst[m[1]] || [] } }];
    }
    if ((m = p.match(/^\/resources\/v1\/modeler\/dsmfg\/dsmfg:MfgItem\/(\w+)$/)))
      return D.items[m[1]] ? [200, { result: { member: [D.items[m[1]]] } }] : [404, { message: "Object not found" }];
    return [404, { message: "no route " + p }];
  }
  var WAFData = { authenticatedRequest: function (url, opts) {
    setTimeout(function () { var r = respond(url, opts); if (r[0] === 200) opts.onComplete(r[1]); else opts.onFailure(new Error("HTTP " + r[0]), r[1]); }, 5);
  } };
  var Compass = { getServiceUrl: function (o) { setTimeout(function () { o.onComplete(SPACE); }, 5); } };
  var dropHandlers = null;
  var DnD = { droppable: function (el, h) { dropHandlers = h; } };
  window.__drop = function (payload) { dropHandlers.drop(JSON.stringify(payload)); };
  var prefs = { x3dPlatformId: D.tenant }, events = {};
  window.widget = { body: document.body, getValue: function (k) { return prefs[k]; }, setValue: function (k, v) { prefs[k] = v; },
    addPreference: function (p) { window.__pref = p; }, addEvent: function (n, f) { events[n] = f; },
    setTitle: function (t) { window.__title = t; } };
  window.require = function (deps, cb) {
    var map = { "DS/WAFData/WAFData": WAFData, "DS/i3DXCompassServices/i3DXCompassServices": Compass, "DS/DataDragAndDrop/DataDragAndDrop": DnD };
    setTimeout(function () { cb.apply(null, deps.map(function (d) { return map[d]; })); }, 0);
  };
})();
