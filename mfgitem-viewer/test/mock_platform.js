// Stand-in for the 3DDashboard runtime, replaying real dsmfg responses from 2026-10-02.
(function () {
  var SPACE = "https://OI000629352-eu1-demo-space.3dexperience.3ds.com/enovia";
  var MA100 = {"name":"mass-OI000629352-00000003","title":"AJ MA 100","description":"","id":"E313E810E8DD0E006ABE8924000020C1","type":"CreateAssembly","modified":"10/1/2026 4:24:14 PM","created":"10/1/2026 4:24:14 PM","revision":"A","state":"IN_WORK","owner":"hjh","organization":"Company Name","collabspace":"Common Space","reservedby":"","outsourced":"1","planningRequired":"2","targetReleaseDate":""};
  var MA101 = {"name":"mass-OI000629352-00000004","title":"AJ MA 101","description":"AJ MA 101","id":"82A2A5E17CDF27006ABFEDFC00010D79","type":"CreateAssembly","modified":"10/2/2026 5:46:36 PM","created":"10/2/2026 5:46:36 PM","revision":"A","state":"IN_WORK","owner":"hjh","organization":"Company Name","collabspace":"Common Space","reservedby":"","outsourced":"1","planningRequired":"2","targetReleaseDate":""};
  var CPR = {"name":"cpr-OI000629352-00000001","title":"Continuous Provided Material00000001","description":"","id":"E313E810E8DD0E006ABF8AF700009C79","type":"ProcessContinuousProvide","revision":"A","state":"IN_WORK","owner":"hjh","organization":"Company Name","collabspace":"Common Space"};
  var MEI = {"id":"E313E8104D0D3D006AC3B32600000479","title":"AJ MEI PP 100","name":"prd-OI000629352-00000002","revision":"A","state":"In Work","manufacturer":"Hi-Tech Supplier","manufacturerPartNumber":"AJ MEI PP 100","type":"Physical Product"};
  var QUALS = {}; QUALS[CPR.id] = [{"id":"05BA445C015A3B006AC3B32B0000167C","type":"SRC Manufacturing Equivalent Qualification","name":"MQ-100000","title":"MQ-100000","state":"In Work","preferred":"FALSE",
      "target":{"id":MEI.id,"type":"Physical Product"},"context":[{"id":CPR.id,"relativePath":"/"+CPR.id}]}];
  window.__sourcingCalls = [];
  window.__ticketCalls = [];
  var FCS = "https://eu1-demo-dfcs.3dexperience.3ds.com/fcs/servlet/fcs/checkout";
  function spec(docId, title, name, rev, fileId, fileName, size) { return { docId: docId, title: title, name: name, rev: rev, fileId: fileId, fileName: fileName, size: size }; }
  var SPECS = {};
  SPECS["E313E810E8DD0E006ABF8AF700009C79"] = [spec("E313E8104D0D3D006AC3CAAE40084476", "00753-2350", "DOC-OI000629352-0000001", "0", "E313E8104D0D3D006AC3CAAE4008448C", "00753-2350.pdf", 1564309)];
  SPECS["E313E810E8DD0E006ABE8924000020C1"] = [spec("D100", "Assembly Work Spec", "DOC-OI000629352-0000002", "A", "F100", "AWS-100.docx", 37472)];
  SPECS["82A2A5E17CDF27006ABFEDFC00010D79"] = [spec("D101", "Tolerances", "DOC-OI000629352-0000003", "A", "F101X", "Tolerances.xlsx", 7254),
                                               spec("D101B", "Old Spec", "DOC-OI000629352-0000004", "B", "F101D", "OldSpec.doc", 10),
                                               spec("D101C", "Blocked spec", "DOC-OI000629352-0000005", "A", "F101B", "Blocked.pdf", 2477)];
  function specDoc(sp) {
    return { id: sp.docId, type: "Document", dataelements: { name: sp.name, title: sp.title, revision: sp.rev, state: "IN_WORK", stateNLS: "In Work", hasDownloadAccess: "TRUE" },
             relateddata: { files: [{ id: sp.fileId, type: "Document", dataelements: { title: sp.fileName, fileSize: String(sp.size) } }] } };
  }
  var ITEMS = {}; [MA100, MA101, CPR].forEach(function (i) { ITEMS[i.id] = i; });
  var BOM = {
    "82A2A5E17CDF27006ABFEDFC00010D79": [{"id":"82A2A5E17CDF27006ABFF43B00010D81","type":"DELFmiFunctionIdentifiedInstance","name":"AJ MA 100.0","referencedObject":{"identifier":MA100.id,"type":"CreateAssembly"}}],
    "E313E810E8DD0E006ABE8924000020C1": [{"id":"E313E810E8DD0E006ABF8B0400009C85","type":"ProcessInstanceContinuous","name":"Continuous Provided Material00000001.0","referencedObject":{"identifier":CPR.id,"type":"ProcessContinuousProvide"}}],
    "E313E810E8DD0E006ABF8AF700009C79": []
  };
  window.__makeCycle = function () { BOM[CPR.id] = [{"id":"CYC1","type":"DELFmiFunctionIdentifiedInstance","name":"AJ MA 101.0","referencedObject":{"identifier":MA101.id,"type":"CreateAssembly"}}]; };
  window.__breakCycle = function () { BOM[CPR.id] = []; };
  window.__calls = [];
  function respond(url, opts) {
    var u = new URL(url), p = u.pathname.replace("/enovia", "");
    if (u.host.indexOf("-sourcing.") >= 0) {
      window.__sourcingCalls.push({ method: opts.method, path: p, csrf: (opts.headers || {}).ENO_CSRF_TOKEN || null, body: opts.data || null, tenant: u.searchParams.get("tenant") });
      if (p === "/resources/v1/application/CSRF") return [200, { csrf: { name: "ENO_CSRF_TOKEN", value: "SRC-TOKEN" } }];
      if (p === "/resources/v1/modeler/dssrc/qualifications/contextLocate") {
        if (opts.method !== "POST") return [405, { title: "Method Not Allowed" }];
        if ((opts.headers || {}).ENO_CSRF_TOKEN !== "SRC-TOKEN") return [403, { message: "CSRF token invalid" }];
        if (window.__failQual) return [500, { message: "Sourcing is down" }];
        var ids = JSON.parse(opts.data).data.map(function (d) { return d.id; });
        var out = []; ids.forEach(function (id) { (QUALS[id] || []).forEach(function (q) { out.push(q); }); });
        return [200, { result: { success: true, statusCode: 200, data: out } }];
      }
      return [404, { message: "no sourcing route " + p }];
    }
    window.__calls.push({ path: p + u.search, ctx: (opts.headers || {}).SecurityContext || null });
    if (u.searchParams.get("tenant") !== "OI000629352") return [403, { message: "tenant missing" }];
    if (p === "/resources/modeler/pno/person")
      return [200, { collabspaces: [{ name: "Common Space", couples: [{ organization: { name: "Company Name" }, role: { name: "VPLMProjectLeader" } }, { organization: { name: "Company Name" }, role: { name: "VPLMCreator" } }] }],
                     preferredcredentials: { collabspace: { name: "Common Space" }, role: { name: "VPLMProjectLeader" }, organization: { name: "Company Name" } } }];
    if (p === "/resources/v1/application/CSRF") return [200, { csrf: { name: "ENO_CSRF_TOKEN", value: "SPACE-TOKEN" } }];
    if (!(opts.headers || {}).SecurityContext) return [401, { message: "SecurityContext required" }];
    if ((m = p.match(/^\/resources\/v1\/modeler\/documents\/parentId\/([0-9A-F]{32})$/))) {
      if (u.searchParams.get("parentRelName") !== "SpecificationDocument") return [200, { success: true, data: [] }];
      if (u.searchParams.get("include") !== "files") return [400, { message: "include=files expected" }];
      return [200, { success: true, statusCode: 200, data: (SPECS[m[1]] || []).map(specDoc) }];
    }
    if ((m = p.match(/^\/resources\/v1\/modeler\/documents\/([^\/]+)\/files\/([^\/]+)\/DownloadTicket$/))) {
      window.__ticketCalls.push({ method: opts.method, doc: m[1], file: m[2], csrf: (opts.headers || {}).ENO_CSRF_TOKEN || null });
      if (opts.method !== "PUT") return [405, { message: "PUT expected" }];
      if ((opts.headers || {}).ENO_CSRF_TOKEN !== "SPACE-TOKEN") return [403, { message: "CSRF token invalid" }];
      return [200, { success: true, data: [{ id: m[1], dataelements: { ticketURL: FCS + "?__fcs__jobTicket=T-" + m[2], fileName: "x" } }] }];
    }
    var m;
    if (p === "/resources/v1/modeler/dssrc/dssrc:ManufacturerEquivalentItems/" + MEI.id)
      return [200, { result: { member: [{ manufacturerPartNumber: MEI.manufacturerPartNumber, partSource: "", partSourceURL: "", IsCustomPart: "No" }] } }];
    if (p === "/resources/v1/modeler/dseng/dseng:EngItem/" + MEI.id)
      return [200, { member: [{ id: MEI.id, title: MEI.title, name: MEI.name, revision: MEI.revision, state: "IN_WORK" }] }];
    if (p === "/resources/v1/modeler/dssrc/dssrc:ManufacturerEquivalentItems/search")
      return [200, { result: { member: (u.searchParams.get("$searchStr") || "").indexOf("AJ MEI") === 0 ? [MEI] : [] } }];
    if (p === "/resources/v1/modeler/dsmfg/dsmfg:MfgItem/search") {
      var q = (u.searchParams.get("$searchStr") || "").toLowerCase();
      if (q.indexOf("<img") === 0) return [200, { result: { member: [{"name":"<b>n</b>","title":"<img src=x onerror=window.__xss=1>","id":"BADBADBADBADBADBADBADBADBADBAD00","type":"CreateAssembly"},MA100] } }];
      var hits = [MA100, MA101, CPR].filter(function (i) { return (i.title + " " + i.name).toLowerCase().indexOf(q) >= 0; });
      return [200, { result: { totalItems: hits.length, member: hits } }];
    }
    if ((m = p.match(/^\/resources\/v1\/modeler\/dsmfg\/dsmfg:MfgItem\/([0-9A-F]{32})\/dsmfg:MfgItemInstance$/)))
      return [200, { result: { member: BOM[m[1]] || [] } }];
    if ((m = p.match(/^\/resources\/v1\/modeler\/dsmfg\/dsmfg:MfgItem\/([0-9A-F]{32})$/)))
      return ITEMS[m[1]] ? [200, { result: { totalItems: 1, member: [ITEMS[m[1]]] } }] : [404, { message: "Object not found" }];
    return [404, { message: "no route " + p }];
  }
  var WAFData = { authenticatedRequest: function (url, opts) {
    setTimeout(function () { var r = respond(url, opts); if (r[0] === 200) opts.onComplete(r[1]); else opts.onFailure(new Error("HTTP " + r[0]), r[1]); }, 20);
  }, proxifiedRequest: function (url, opts) {
    window.__proxyCalls = (window.__proxyCalls || 0) + 1;
    setTimeout(function () {
      var id = (url.match(/jobTicket=T-(.*)$/) || [])[1], b64 = (window.__proxyBytes || {})[id];
      if (!b64) return opts.onFailure(new Error("proxy refused"));
      var bin = atob(b64), arr = new Uint8Array(bin.length); for (var i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
      opts.onComplete(arr.buffer);
    }, 20);
  }};
  var SOURCING = "https://oi000629352-eu1-demo-sourcing.3dexperience.3ds.com/enovia";
  var Compass = { getServiceUrl: function (o) { setTimeout(function () {
    if (o.serviceName === "Sourcing") { if (window.__noSourcingRegistry) return o.onFailure && o.onFailure("unknown service"); return o.onComplete(SOURCING); }
    o.onComplete(SPACE); }, 10); } };
  var dropHandlers = null;
  var DnD = { droppable: function (el, h) { dropHandlers = h; } };
  window.__drop = function (payload) { dropHandlers.drop(JSON.stringify(payload)); };
  var prefs = { x3dPlatformId: "OI000629352" }, events = {};
  window.widget = { body: document.body, getValue: function (k) { return prefs[k]; }, setValue: function (k, v) { prefs[k] = v; },
    addPreference: function (p) { window.__pref = p; }, addEvent: function (n, f) { events[n] = f; },
    setTitle: function (t) { window.__title = t; } };
  // like the dashboard: an AMD define() is present (jsPDF must not be captured by it)
  window.define = function () { window.__anonDefine = (window.__anonDefine || 0) + 1; }; window.define.amd = {};
  window.require = function (deps, cb, errb) {
    if (window.__failRequire) { setTimeout(function () { errb && errb({ requireModules: deps }); }, 0); return; }
    var map = { "DS/WAFData/WAFData": WAFData, "DS/i3DXCompassServices/i3DXCompassServices": Compass, "DS/DataDragAndDrop/DataDragAndDrop": DnD };
    setTimeout(function () { cb.apply(null, deps.map(function (d) { return map[d]; })); }, 0);
  };
})();
