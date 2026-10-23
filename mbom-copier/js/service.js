/*
 * MBOM Copier - service: calls to the MBOM Copier service running on this PC
 * (python mbom_service.py) and the Settings screen.
 *
 * The service address and pairing token are kept in this browser only (localStorage),
 * never in the dashboard. Passwords and agent keys are sent once to the service, which
 * writes them to target.env on the PC; it never sends them back.
 */
(function (M) {
  "use strict";
  var esc = M.esc;
  var DEFAULT_URL = "http://127.0.0.1:8765";

  function store(k, v) {
    try {
      if (v === undefined) return window.localStorage.getItem("mbc." + k);
      window.localStorage.setItem("mbc." + k, v);
    } catch (noStorage) { M.mem = M.mem || {}; if (v === undefined) return M.mem[k]; M.mem[k] = v; }
    return v;
  }
  M.serviceUrl = function () { return (store("service") || DEFAULT_URL).replace(/\/$/, ""); };
  M.serviceToken = function () { return store("token") || ""; };

  M.svc = function (method, path, body) {
    var opts = { method: method, headers: { "X-MBC-Token": M.serviceToken() }, cache: "no-store" };
    if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    return fetch(M.serviceUrl() + path, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (r.ok) return data;
        var err = new Error((data && data.error) || ("The service answered HTTP " + r.status + "."));
        err.status = r.status;
        throw err;
      });
    }, function () {
      var err = new Error("The MBOM Copier service is not reachable at " + M.serviceUrl() + ". Check that it is running on this PC " +
        "(python mbom_service.py in the mbom-copier folder). If it is, the browser blocked the call: allow \"local network access\" " +
        "when Chrome/Edge asks (the lock icon left of the address bar shows the setting).");
      err.offline = true;
      throw err;
    });
  };

  // ---------- connection state shown in the bar ----------
  M.target = null;              // target summary from the service
  M.checkService = function () {
    var ui = M.ui;
    ui.svc.className = "svc";
    ui.svc.textContent = "Service: checking…";
    return M.svc("GET", "/status").then(function (st) {
      M.target = st.target;
      M.serviceOk = true;
      ui.svc.className = "svc " + (st.target.configured ? "ok" : "warn");
      ui.svc.textContent = st.target.configured ? "Target: " + st.target.tenant + " (" + st.target.username + ")" : "Target not set up — open Settings";
      M.refreshButtons();
      return st;
    }, function (e) {
      M.serviceOk = false; M.target = null;
      ui.svc.className = "svc bad";
      ui.svc.textContent = e.offline ? "Service not running" : e.status === 401 ? "Service: pairing token needed" : "Service: " + e.message;
      ui.svc.title = e.message;
      M.refreshButtons();
      throw e;
    });
  };

  // ---------- Settings screen ----------
  function field(label, html, hint) {
    return "<label class='f'><span>" + esc(label) + "</span>" + html + (hint ? "<small>" + esc(hint) + "</small>" : "") + "</label>";
  }
  M.openSettings = function () {
    var ui = M.ui, t = M.target || {};
    ui.settings.style.display = "";
    ui.main.style.display = "none";
    ui.settings.innerHTML =
      "<div class='title'>Settings</div>" +
      "<h3>Service on this PC</h3>" +
      field("Address", "<input name='service' value='" + esc(M.serviceUrl()) + "'/>", "Shown when you start python mbom_service.py.") +
      field("Pairing token", "<input name='token' type='password' autocomplete='off' value='" + esc(M.serviceToken()) + "'/>",
            "Also shown in the service window. Kept in this browser only.") +
      "<div class='row'><span class='btn sec' data-act='svc-save' role='button' tabindex='0' aria-disabled='false'>Save &amp; check</span></div>" +
      "<h3>Target tenant</h3>" +
      "<p class='sub'>Kept by the service in target.env on this PC. The password and agent key are never shown again; leave them blank to keep the stored ones.</p>" +
      field("Tenant address", "<input name='tenant_url' placeholder='https://r1132100000770-us1-ifwe.3dexperience.3ds.com/' value='" +
            esc(t.apigateway_url ? t.apigateway_url.replace("-apigateway.", "-ifwe.") + "/" : "") + "'/>",
            "Any address of the target tenant, e.g. its dashboard URL.") +
      field("3DPassport username", "<input name='username' autocomplete='off' value='" + esc(t.username || "") + "'/>") +
      field("Password", "<input name='password' type='password' autocomplete='new-password' placeholder='" +
            (t.has_password ? "stored — leave blank to keep" : "") + "'/>") +
      field("Security context", "<input name='security_context' placeholder='Role.Organization.Collaborative space' value='" + esc(t.security_context || "") + "'/>",
            "Internal names, e.g. VPLMProjectLeader.Company Name.Common Space.") +
      field("Connection", "<select name='server_preference'><option value='APIGateway'>API Gateway (agent key)</option>" +
            "<option value='3DSpace'>3DSpace (login only)</option></select>") +
      field("Agent key", "<input name='api_key' type='password' autocomplete='off' placeholder='" +
            (t.has_api_key ? "stored — leave blank to keep" : "key of the agent in Agent Management") + "'/>",
            "The agent's key, not its ID. Only used with API Gateway.") +
      "<div class='row'><span class='btn' data-act='tgt-save' role='button' tabindex='0' aria-disabled='false'>Save</span>" +
      "<span class='btn sec' data-act='tgt-test' role='button' tabindex='0' aria-disabled='false'>Test connection</span>" +
      "<span class='btn sec' data-act='close' role='button' tabindex='0' aria-disabled='false'>Close</span></div>" +
      "<div class='sstat status'></div>";
    var sel = ui.settings.querySelector("select[name=server_preference]");
    sel.value = t.server_preference || "APIGateway";
  };
  M.closeSettings = function () { M.ui.settings.style.display = "none"; M.ui.main.style.display = ""; };

  function val(name) { var e = M.ui.settings.querySelector("[name=" + name + "]"); return e ? e.value.trim() : ""; }
  function sstat(msg, err) {
    var s = M.ui.settings.querySelector(".sstat");
    if (s) { s.textContent = msg; s.className = "sstat status" + (err ? " error" : ""); }
  }

  M.settingsAction = function (act) {
    if (act === "close") return M.closeSettings();
    if (act === "svc-save") {
      store("service", val("service") || DEFAULT_URL);
      store("token", val("token"));
      sstat("Checking the service…");
      return M.checkService().then(function (st) {
        M.openSettingsKeep();       // refresh the target fields from the service, then say what happened
        sstat("Service " + st.version + " reached." + (st.target.configured ? " Target " + st.target.tenant + " is set up." : " Now fill in the target."));
      }, function (e) { sstat(e.message, true); });
    }
    if (act === "tgt-save" || act === "tgt-test") {
      var body = { username: val("username"), security_context: val("security_context"),
                   server_preference: val("server_preference") };
      if (val("tenant_url")) body.tenant_url = val("tenant_url");
      if (val("password")) body.password = val("password");
      if (val("api_key")) body.api_key = val("api_key");
      sstat("Saving…");
      return M.svc("POST", "/settings", body).then(function (s) {
        M.target = s;
        var pw = M.ui.settings.querySelector("[name=password]"), key = M.ui.settings.querySelector("[name=api_key]");
        pw.value = ""; key.value = "";
        if (s.has_password) pw.placeholder = "stored — leave blank to keep";
        if (s.has_api_key) key.placeholder = "stored — leave blank to keep";
        if (act === "tgt-save") { sstat("Saved for " + s.tenant + "."); return M.checkService(); }
        sstat("Saved. Signing in to " + s.tenant + "…");
        return M.svc("POST", "/settings/test").then(function (r) {
          sstat("Connected to " + r.tenant + ": sign-in and search work.");
          return M.checkService();
        });
      }).catch(function (e) { sstat(e.message, true); });
    }
  };
  // re-render with the latest summary but keep what the user typed in the service fields
  M.openSettingsKeep = function () {
    var svcUrl = val("service"), tok = val("token");
    M.openSettings();
    M.ui.settings.querySelector("[name=service]").value = svcUrl || M.serviceUrl();
    M.ui.settings.querySelector("[name=token]").value = tok || M.serviceToken();
  };
})(window.MBC);
