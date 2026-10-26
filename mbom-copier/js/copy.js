/*
 * MBOM Copier - copy: Dry run (the service checks the target and returns the plan),
 * Copy (the service creates it in the background) and progress polling.
 */
(function (M) {
  "use strict";

  function options() { return { reuse_existing: !!M.ui.reuse.checked, title_suffix: M.ui.suffix.value || "" }; }

  M.dryRun = function () {
    if (!M.src || M.busy) return;
    var opt = options();
    var loading = M.ASSOC_KINDS.filter(function (k) { return M.assocOptions()[k.key] && M.src.assocState && M.src.assocState[k.key] === "loading"; });
    if (loading.length) return M.setStatus("Still reading " + loading.map(function (k) { return k.label; }).join(", ") + " from the source — try again in a moment.", true);
    var body = { source_tenant: M.src.tenant, root: M.src.rootId, items: M.src.items, children: M.src.children,
                 reuse_existing: opt.reuse_existing, title_suffix: opt.title_suffix };
    var assoc = M.assocPayload();
    if (assoc) body.assoc = assoc;
    M.busy = true; M.refreshButtons();
    M.setStatus("Checking " + ((M.target && M.target.tenant) || "the target") + "…");
    return M.svc("POST", "/plan", body).then(function (v) {
      M.busy = false;
      M.show(v);
    }, function (e) { M.busy = false; M.refreshButtons(); M.setStatus(e.message, true); });
  };

  // a plan / run view from the service -> table, summary, buttons
  M.show = function (v) {
    M.plan = v;
    M.renderTable(v.rows);
    var c = v.counts, ui = M.ui;
    var parts = [];
    if (c.create || c.inst_create) parts.push("To create in " + v.target + ": " + c.create + " item" + (c.create === 1 ? "" : "s") + ", " +
                                              c.inst_create + " instance" + (c.inst_create === 1 ? "" : "s"));
    if (c.created || c.inst_created) parts.push((v.status === "done" ? "Created in " + v.target + ": " : "already created: ") +
                                                c.created + " items, " + c.inst_created + " instances");
    if (c.reuse) parts.push("reused from the target: " + c.reuse + (c.inside ? " (+" + c.inside + " inside them, not copied)" : ""));
    if (c.assoc) {
      var a = c.assoc, ap = [];
      M.ASSOC_KINDS.forEach(function (k) {
        var x = a[k.key];
        if (!x || !(x.pending + x.done + x.error + x.skip + (x.waiting || 0))) return;
        var bits = [];
        if (x.done) bits.push(x.done + " done");
        if (x.pending + x.error) bits.push((x.pending + x.error) + " to link");
        if (x.waiting) bits.push(x.waiting + " waiting for the API spec");
        if (x.skip) bits.push(x.skip + " skipped");
        ap.push(k.label + ": " + bits.join(", "));
      });
      var nw = a.new || {};
      var made = [nw.docs ? nw.docs + " new document" + (nw.docs === 1 ? "" : "s") : "", nw.meis ? nw.meis + " new MEI" + (nw.meis === 1 ? "" : "s") : "",
                  nw.cas ? nw.cas + " new change action" + (nw.cas === 1 ? "" : "s") : ""].filter(Boolean);
      if (ap.length) parts.push(ap.join(" · ") + (made.length ? " — " + made.join(", ") : ""));
    }
    ui.summary.innerHTML = "";
    ui.summary.appendChild(M.el("div", "sumline", parts.join(" · ") || "Nothing to create: everything already exists in " + v.target + "."));
    (v.warnings || []).forEach(function (w) { ui.summary.appendChild(M.el("div", "warn", "⚠ " + w)); });
    var ev = v.events || [];
    ui.log.textContent = ev.join("\n");
    ui.log.style.display = ev.length ? "" : "none";
    if (v.status === "running") M.setStatus("Copying to " + v.target + "… (" + (c.created + c.inst_created) + " steps done)");
    else if (v.status === "done") M.setStatus("Copied: " + rootDone(v) + " The target structure matches the source.");
    else if (v.status === "incomplete") M.setStatus(c.failed + " step" + (c.failed === 1 ? "" : "s") + " failed — see the red rows. Fix the cause and press Copy again; finished steps are skipped.", true);
    else if (v.status === "copied with differences") M.setStatus("Copied, but the target differs from the source: " + ((v.verification || {}).problems || []).join("; "), true);
    else if (v.status === "failed") M.setStatus("The copy stopped: " + (v.error || "unknown error") + ". Press Copy again to continue.", true);
    else M.setStatus((c.create || c.inst_create || c.assoc_todo) ? "Dry run done — nothing was written. Check the plan, then press Copy." : "Nothing to copy.");
    M.refreshButtons();
  };
  function rootDone(v) {
    var r = v.rows[0];
    return r.title + " is " + (r.target_name || r.target_id) + " in " + v.target + ".";
  }

  // Copy needs a second click within 8 s: it writes to the target tenant
  var armed = null;
  M.copy = function () {
    var v = M.plan, ui = M.ui;
    if (!v || M.busy) return;
    if (!armed) {
      armed = setTimeout(function () { armed = null; M.refreshButtons(); }, 8000);
      ui.copy.textContent = "Click again to create " + v.counts.create + " items, " + v.counts.inst_create + " instances" +
        (v.counts.assoc_todo ? " and " + v.counts.assoc_todo + " associations" : "") + " in " + v.target;
      ui.copy.className = "btn danger";
      return;
    }
    clearTimeout(armed); armed = null;
    M.busy = true; M.refreshButtons();
    M.setStatus("Starting the copy…");
    var files = v.files_needed || [];
    (files.length ? M.sendFiles(v.run, files) : Promise.resolve()).then(function () {
      return M.svc("POST", "/execute", { run: v.run });
    }).then(function (r) { M.show(r); poll(r.run); },
      function (e) { M.busy = false; M.refreshButtons(); M.setStatus(e.message, true); });
  };
  function poll(run) {
    M.svc("GET", "/runs/" + encodeURIComponent(run)).then(function (r) {
      M.show(r);
      if (r.status === "running") return setTimeout(function () { poll(run); }, 1000);
      M.busy = false; M.refreshButtons();
    }, function (e) {
      // keep trying for a short service hiccup; the copy itself keeps running on the PC
      M.setStatus(e.message + " Retrying…", true);
      setTimeout(function () { poll(run); }, 3000);
    });
  }
  M.copyLabel = function () {
    var v = M.plan;
    if (armed) return null;
    return v && v.status === "incomplete" || v && v.status === "failed" ? "Copy again (finish)" : "Copy to " + ((v && v.target) || "target");
  };
})(window.MBC);
