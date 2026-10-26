// Stand-in for the 3DDashboard runtime (source tenant). window.__SRC = { tenant, items: {id: item}, inst: {id: [instance]} }
// is injected by run_test.py from the same data the Python tests use.
(function () {
  var D = window.__SRC, SPACE = "https://" + D.tenant.toLowerCase() + "-eu1-demo-space.3dexperience.3ds.com/enovia";
  var SOURCING = SPACE.replace("-space.", "-sourcing.");
  var A = D.assoc || {};                    // associated objects of the source items (run_assoc_test.py)
  window.__calls = [];
  var CSRF = { csrf: { name: "ENO_CSRF_TOKEN", value: "TOKEN" } };
  // the only non-GET calls the widget may make: reads that need POST/PUT (Sourcing lookup, download ticket)
  var READ_ONLY_POSTS = [/\/qualifications\/contextLocate$/, /\/files\/\w+\/DownloadTicket$/];
  function respond(url, opts) {
    var u = new URL(url), p = u.pathname.replace("/enovia", ""), m;
    window.__calls.push({ method: opts.method, path: p, ctx: (opts.headers || {}).SecurityContext || null, host: u.host });
    if (u.searchParams.get("tenant") !== D.tenant) return [403, { message: "tenant missing" }];
    if (p === "/resources/v1/application/CSRF") return [200, CSRF];
    if (opts.method !== "GET" && !READ_ONLY_POSTS.some(function (r) { return r.test(p); }))
      return [405, { message: "the widget must not write to the source" }];
    if (opts.method !== "GET" && (opts.headers || {}).ENO_CSRF_TOKEN !== "TOKEN") return [403, { message: "CSRF token missing" }];
    if (u.host.indexOf("-sourcing.") >= 0) {
      if (p !== "/resources/v1/modeler/dssrc/qualifications/contextLocate") return [404, { message: "no sourcing route " + p }];
      var ids = JSON.parse(opts.data).data.map(function (x) { return x.id; });
      return [200, { result: { success: true, data: (A.quals || []).filter(function (q) {
        return q.contexts.some(function (c) { return ids.indexOf(c.id) >= 0; }); }) } }];
    }
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
    if ((m = p.match(/^\/resources\/v1\/modeler\/documents\/parentId\/(\w+)$/))) {
      if (u.searchParams.get("parentRelName") !== "SpecificationDocument" || u.searchParams.get("include") !== "files") return [400, { message: "bad query" }];
      return [200, { success: true, data: (A.docs && A.docs[m[1]]) || [] }];
    }
    if ((m = p.match(/^\/resources\/v1\/modeler\/documents\/(\w+)\/files\/(\w+)\/DownloadTicket$/)))
      return [200, { success: true, data: [{ id: m[1], dataelements: { ticketURL: "https://eu1-demo-dfcs.3dexperience.3ds.com/fcs/servlet/fcs/checkout?__fcs__jobTicket=T-" + m[2] } }] }];
    if ((m = p.match(/^\/resources\/v1\/modeler\/dsmfg\/dsmfg:MfgItem\/(\w+)\/dsmfg:MfgResponsibility$/)))
      return [200, { member: (A.resp && A.resp[m[1]]) || [] }];
    if ((m = p.match(/^\/resources\/v1\/modeler\/organizations\/(\w+)$/)))
      return A.orgs && A.orgs[m[1]] ? [200, { member: [A.orgs[m[1]]] }] : [404, { message: "no org" }];
    if ((m = p.match(/^\/resources\/v1\/modeler\/dsmfg\/dsmfg:MfgItem\/(\w+)\/dslc:changeImpact$/)))
      return [200, { member: [{ "Impacting Objects": (A.impact && A.impact[m[1]]) || [] }] }];
    if ((m = p.match(/^\/resources\/v1\/modeler\/dslc\/changeaction\/(\w+)$/)))
      return A.cas && A.cas[m[1]] ? [200, A.cas[m[1]]] : [404, { message: "no CA" }];
    if (p === "/resources/v1/modeler/dssrc/dssrc:ManufacturerEquivalentItems/search") {
      var s = u.searchParams.get("$searchStr");
      return [200, { result: { member: Object.keys(A.meis || {}).map(function (k) { return A.meis[k]; })
        .filter(function (x) { return x.manufacturerPartNumber === s; }) } }];
    }
    if ((m = p.match(/^\/resources\/v1\/modeler\/dssrc\/dssrc:ManufacturerEquivalentItems\/(\w+)$/)))
      return A.meis && A.meis[m[1]] ? [200, { result: { member: [{ manufacturerPartNumber: A.meis[m[1]].manufacturerPartNumber, partSource: "" }] } }] : [404, {}];
    if ((m = p.match(/^\/resources\/v1\/modeler\/dseng\/dseng:EngItem\/(\w+)$/)))
      return A.meis && A.meis[m[1]] ? [200, { member: [{ id: m[1], title: A.meis[m[1]].title, name: A.meis[m[1]].name, revision: "A" }] }] : [404, {}];
    if ((m = p.match(/^\/resources\/v1\/modeler\/dsmfg\/dsmfg:MfgItem\/(\w+)$/)))
      return D.items[m[1]] ? [200, { result: { member: [D.items[m[1]]] } }] : [404, { message: "Object not found" }];
    return [404, { message: "no route " + p }];
  }
  var WAFData = { authenticatedRequest: function (url, opts) {
    setTimeout(function () { var r = respond(url, opts); if (r[0] === 200) opts.onComplete(r[1]); else opts.onFailure(new Error("HTTP " + r[0]), r[1]); }, 5);
  } };
  var Compass = { getServiceUrl: function (o) { setTimeout(function () { o.onComplete(o.serviceName === "Sourcing" ? SOURCING : SPACE); }, 5); } };
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
