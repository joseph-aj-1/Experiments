/*
 * Route Viewer - core: shared namespace (window.RTV), helpers, platform requests
 * (WAFData = the signed-in user's session) and the security context.
 */
(function () {
  "use strict";
  var M = window.RTV = window.RTV || {};

  M.app = { space: null, usersgroup: null, ctx: null, tenant: null, view: null };
  M.loadSeq = 0;            // incremented per opened route; late results for an older route are ignored
  M.ready = false;

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
  M.data = function (resp) { var r = resp && (resp.result || resp); return (r && r.data) || []; };
  // "2026-10-07T15:49:53.000Z" or "10/6/2026 3:50:03 PM" -> "Wednesday, October 7, 2026"
  M.fmtDate = function (v, withTime) {
    if (!v) return "";
    var d = new Date(v);
    if (isNaN(d.getTime())) return String(v);
    var o = { weekday: "long", year: "numeric", month: "long", day: "numeric" };
    if (withTime) { o.hour = "2-digit"; o.minute = "2-digit"; }
    try { return withTime ? d.toLocaleString(undefined, o) : d.toLocaleDateString(undefined, o); } catch (ignored) { return d.toDateString(); }
  };

  // ---------- status line ----------
  M.setStatus = function (msg, isError) {
    if (!M.ui) return;
    M.ui.status.textContent = msg || "";
    M.ui.status.className = "status" + (isError ? " error" : "");
  };
  M.lastStep = "loading platform modules";
  M.step = function (s) { M.lastStep = s; M.setStatus(s.charAt(0).toUpperCase() + s.slice(1) + "…"); };

  // ---------- platform requests ----------
  function withTenant(url) {
    if (!M.app.tenant) return url;
    return url + (url.indexOf("?") < 0 ? "?" : "&") + "tenant=" + encodeURIComponent(M.app.tenant);
  }
  // opts: { ctx: false } to leave out the SecurityContext header (needed only by 3DSpace)
  M.request = function (method, url, body, opts) {
    opts = opts || {};
    return new Promise(function (resolve, reject) {
      var headers = { Accept: "application/json" };
      if (opts.ctx !== false && M.app.ctx) headers.SecurityContext = M.app.ctx;
      if (body != null) headers["Content-Type"] = "application/json";
      M.WAFData.authenticatedRequest(withTenant(url), {
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
  M.get = function (path, opts) { return M.request("GET", M.app.space + path, null, opts); };

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
    return M.get("/resources/modeler/pno/person?current=true&select=collabspaces&select=preferredcredentials", { ctx: false })
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
