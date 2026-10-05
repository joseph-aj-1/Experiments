/*
 * Mfg Item Viewer - core: shared namespace, helpers, platform requests, security context.
 * Every file adds to window.MFV; main.js wires everything together in MFV.start().
 */
(function () {
  "use strict";
  var M = window.MFV = window.MFV || {};

  // shared state
  M.app = { space: null, sourcing: null, ctx: null, tenant: null, view: null };
  M.loadSeq = 0;          // incremented per opened item; late results for an older item are ignored
  M.ready = false;

  M.TYPE_LABELS = {
    CreateAssembly: "Manufacturing Assembly",
    ProcessContinuousProvide: "Continuous Provided Material",
    Provide: "Provided Part",
    CreateMaterial: "Manufactured Material",
    CreateKit: "Kit",
    DELFmiFunctionIdentifiedInstance: "Instance",
    ProcessInstanceContinuous: "Continuous Instance"
  };
  M.STATE_LABELS = { IN_WORK: "In Work", "In Work": "In Work", FROZEN: "Frozen", RELEASED: "Released", OBSOLETE: "Obsolete", PRIVATE: "Private" };

  // ---------- small helpers ----------
  M.esc = function (v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };
  M.el = function (tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  };
  M.typeLabel = function (t) { return M.TYPE_LABELS[t] || t || ""; };
  M.stateLabel = function (s) { return M.STATE_LABELS[s] || s || ""; };
  M.yesNo = function (v) { return v === "2" ? "Yes" : v === "1" ? "No" : (v === true ? "Yes" : v === false ? "No" : (v || "")); };
  M.extOf = function (name) { var m = /\.([A-Za-z0-9]{1,5})$/.exec(name || ""); return m ? m[1].toLowerCase() : ""; };
  M.fmtSize = function (n) {
    n = +n || 0;
    return n >= 1048576 ? (n / 1048576).toFixed(1) + " MB" : n >= 1024 ? Math.round(n / 1024) + " KB" : n ? n + " B" : "";
  };
  // Standard PDF fonts only cover basic Latin: map the few special characters we use.
  M.pdfText = function (v) {
    return String(v == null ? "" : v).replace(/[—–]/g, "-").replace(/…/g, "...").replace(/[·•]/g, "-")
      .replace(/[‘’]/g, "'").replace(/[“”]/g, '"').replace(/[^\x09\x0a\x0d\x20-\x7e\xa0-\xff]/g, "");
  };
  M.stamp = function () {
    var d = new Date(), z = function (n) { return (n < 10 ? "0" : "") + n; };
    return { file: d.getFullYear() + z(d.getMonth() + 1) + z(d.getDate()) + "-" + z(d.getHours()) + z(d.getMinutes()),
             text: d.getFullYear() + "-" + z(d.getMonth() + 1) + "-" + z(d.getDate()) + " " + z(d.getHours()) + ":" + z(d.getMinutes()) };
  };
  // run fn over list with at most `limit` in flight; failures become { error }
  M.mapLimit = function (list, limit, fn) {
    var out = new Array(list.length), i = 0;
    function next() {
      if (i >= list.length) return Promise.resolve();
      var k = i++;
      return Promise.resolve(fn(list[k], k)).then(function (r) { out[k] = r; }, function (e) { out[k] = { error: e }; }).then(next);
    }
    var runners = [];
    for (var n = 0; n < Math.min(limit, list.length); n++) runners.push(next());
    return Promise.all(runners).then(function () { return out; });
  };
  M.members = function (resp) { var r = resp && (resp.result || resp); return (r && r.member) || []; };
  M.docData = function (resp) { var r = resp && (resp.result || resp); return (r && r.data) || []; };

  // ---------- status line ----------
  M.setStatus = function (msg, isError) {
    if (!M.ui) return;
    M.ui.status.textContent = msg || "";
    M.ui.status.className = "status" + (isError ? " error" : "");
  };
  M.lastStep = "loading platform modules";
  M.step = function (s) { M.lastStep = s; M.setStatus(s.charAt(0).toUpperCase() + s.slice(1) + "…"); };

  // ---------- platform requests (WAFData = signed-in user's session) ----------
  M.withTenant = function (url) {
    if (!M.app.tenant) return url;
    return url + (url.indexOf("?") < 0 ? "?" : "&") + "tenant=" + encodeURIComponent(M.app.tenant);
  };
  M.request = function (method, url, body, withCtx, extraHeaders) {
    return new Promise(function (resolve, reject) {
      var headers = { Accept: "application/json" };
      if (withCtx !== false && M.app.ctx) headers.SecurityContext = M.app.ctx;
      if (body != null) headers["Content-Type"] = "application/json";
      Object.keys(extraHeaders || {}).forEach(function (k) { headers[k] = extraHeaders[k]; });
      M.WAFData.authenticatedRequest(M.withTenant(url), {
        method: method, type: "json", headers: headers,
        data: body != null ? JSON.stringify(body) : undefined,
        onComplete: function (data) { resolve(data); },
        onFailure: function (err, respBody) {
          var detail = "";
          try { detail = (respBody && (respBody.message || respBody.error || JSON.stringify(respBody))) || (err && err.message) || ""; } catch (ignored) { detail = ""; }
          reject(new Error("Request failed" + (detail ? ": " + detail : "")));
        },
        onPassportError: function () { reject(new Error("Not signed in to 3DPassport.")); },
        onTimeout: function () { reject(new Error("The request timed out.")); }
      });
    });
  };
  M.get = function (path, withCtx) { return M.request("GET", M.app.space + path, null, withCtx); };

  // ---------- security context (role.organization.collabspace) ----------
  function contextOptions(person) {
    var out = [];
    (person.collabspaces || []).forEach(function (cs) {
      (cs.couples || []).forEach(function (c) {
        if (c.role && c.organization && cs.name) out.push(c.role.name + "." + c.organization.name + "." + cs.name);
      });
    });
    return out;
  }
  function preferredContext(person) {
    var p = person.preferredcredentials;
    if (p && p.role && p.organization && p.collabspace) return p.role.name + "." + p.organization.name + "." + p.collabspace.name;
    return null;
  }
  M.loadContext = function () {
    var w = M.w;
    M.step("reading your roles and collaborative spaces");
    return M.get("/resources/modeler/pno/person?current=true&select=collabspaces&select=preferredcredentials", false)
      .then(function (person) {
        var opts = contextOptions(person);
        var saved = w.getValue("securityContext");
        var chosen = (saved && opts.indexOf(saved) >= 0) ? saved : (preferredContext(person) || opts[0]);
        if (!chosen) throw new Error("No role/collaborative space found for your account.");
        if (opts.length && w.addPreference) {
          w.addPreference({
            name: "securityContext", type: "list", label: "Security context", defaultValue: chosen,
            options: opts.map(function (o) { return { label: o, value: o }; })
          });
        }
        M.app.ctx = "ctx::" + chosen;
        M.ui.ctx.textContent = "Context: " + chosen;
      });
  };
})();
