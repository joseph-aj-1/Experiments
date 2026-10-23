/*
 * MBOM Copier - ui: layout (search/drop bar, connection line, options, structure table,
 * progress log, Settings panel), the table renderer and button states.
 * The dashboard may strip markup from the widget body, so everything is built here.
 */
(function (M) {
  "use strict";
  var el = M.el, esc = M.esc;

  function button(cls, text, title) {
    var b = el("span", "btn " + cls, text);
    b.setAttribute("role", "button"); b.setAttribute("tabindex", "0"); b.setAttribute("aria-disabled", "true");
    if (title) b.setAttribute("title", title);
    return b;
  }
  M.enable = function (b, on) { b.setAttribute("aria-disabled", on ? "false" : "true"); };

  M.buildUi = function (root) {
    var ui = {};
    ui.wrap = el("div", "mbc");
    var bar = el("div", "bar");
    ui.q = el("input"); ui.q.type = "text"; ui.q.placeholder = "Title, name or physical ID of the top Manufacturing Item";
    ui.go = button("go", "Search");
    ui.gear = button("sec gear", "⚙ Settings", "Service on this PC and target tenant");
    M.enable(ui.gear, true);
    bar.appendChild(ui.q); bar.appendChild(ui.go); bar.appendChild(ui.gear);
    ui.drop = el("div", "drop", "Drop a Manufacturing Item here (from MBOM / Manufactured Item Definition or search)");
    var conn = el("div", "conn");
    ui.ctx = el("span", "ctx");
    ui.svc = el("span", "svc", "Service: checking…");
    conn.appendChild(ui.ctx); conn.appendChild(ui.svc);
    ui.status = el("div", "status", "Starting (v" + M.version + ")…");
    ui.results = el("div", "results");

    ui.main = el("div", "main");
    var opts = el("div", "opts");
    var lab = el("label", "chk");
    ui.reuse = el("input"); ui.reuse.type = "checkbox";
    lab.appendChild(ui.reuse); lab.appendChild(document.createTextNode(" Reuse target items with the same title and type"));
    var sl = el("label", "suf", "Title suffix ");
    ui.suffix = el("input"); ui.suffix.type = "text"; ui.suffix.placeholder = "optional, e.g. (copy)";
    sl.appendChild(ui.suffix);
    ui.dry = button("go", "Dry run", "Check the target and show what would be created. Nothing is written.");
    ui.copy = button("danger", "Copy to target", "Create the copy in the target tenant");
    [lab, sl, ui.dry, ui.copy].forEach(function (n) { opts.appendChild(n); });
    ui.summary = el("div", "summary");
    ui.table = el("div", "tablewrap");
    ui.log = el("pre", "log"); ui.log.style.display = "none";
    [opts, ui.summary, ui.table, ui.log].forEach(function (n) { ui.main.appendChild(n); });

    ui.settings = el("div", "settings"); ui.settings.style.display = "none";
    [bar, ui.drop, conn, ui.status, ui.results, ui.main, ui.settings].forEach(function (n) { ui.wrap.appendChild(n); });
    root.innerHTML = "";
    root.style.margin = "0"; root.style.padding = "0"; root.style.overflow = "hidden";
    root.appendChild(ui.wrap);
    M.ui = ui;
    return ui;
  };

  var ACTION = { create: "Create", reuse: "Reuse", inside: "—", done: "Done", "": "" };
  M.renderTable = function (rows) {
    var ui = M.ui;
    if (!rows) { ui.table.innerHTML = ""; ui.summary.innerHTML = ""; ui.log.style.display = "none"; return; }
    var planned = rows.some(function (r) { return r.action; });
    var head = "<tr><th>Level</th><th>Structure</th><th>Instance</th><th>Qty</th><th>Name</th><th>Type</th><th>Rev</th>" +
               (planned ? "<th>Action</th><th>Target</th>" : "") + "</tr>";
    var body = rows.map(function (r) {
      var err = r.error || r.instance_error;
      var act = r.repeat ? "" : (r.error ? "Failed" : ACTION[r.action] || r.action || "");
      var instMark = r.instance_status === "done" ? " ✓" : r.instance_status === "error" ? " ✗" : "";
      var tgt = r.repeat ? "" : (r.target_name || (r.action === "create" && r.target_title !== r.title ? r.target_title : ""));
      var note = r.repeat ? "<span class='note'>(same item as above)</span>" : "";
      var tip = [r.note, err].filter(Boolean).join(" — ");
      return "<tr class='lvl" + Math.min(r.level, 9) + (err ? " err" : "") + (planned && !r.repeat ? " a-" + (r.error ? "error" : r.action) : "") +
        "'" + (tip ? " title='" + esc(tip) + "'" : "") + ">" +
        "<td class='lvl'>" + r.level + "</td>" +
        "<td class='tree' style='padding-left:" + (6 + r.level * 18) + "px'>" + (r.level ? "<span class='elbow'>└─</span>" : "") +
          esc(r.title) + " " + note + (r.note && !r.repeat ? " <span class='flag' title='" + esc(r.note) + "'>!</span>" : "") + "</td>" +
        "<td>" + esc(r.instance || "") + (planned ? "<span class='im'>" + instMark + "</span>" : "") + "</td>" +
        "<td class='qty'>" + esc(M.qtyOf(r.quantity) || (typeof r.quantity === "string" ? r.quantity : "")) + "</td>" +
        "<td>" + esc(r.name) + "</td><td>" + esc(r.type_label || M.typeLabel(r.type)) + "</td><td>" + esc(r.revision || "") + "</td>" +
        (planned ? "<td class='act'>" + esc(act) + "</td><td>" + esc(tgt) + "</td>" : "") + "</tr>" +
        (err && !r.repeat ? "<tr class='errline'><td></td><td colspan='" + (planned ? 8 : 6) + "'>" + esc(err) + "</td></tr>" : "");
    }).join("");
    ui.table.innerHTML = "<table class='bom'><thead>" + head + "</thead><tbody>" + body + "</tbody></table>";
  };

  M.refreshButtons = function () {
    var ui = M.ui, v = M.plan, ready = M.serviceOk && M.target && M.target.configured;
    M.enable(ui.go, M.ready && !M.busy);
    M.enable(ui.dry, !!(M.src && ready && !M.busy));
    ui.dry.title = !M.src ? "Drop or search an item first" : !ready ? "Set up the service and target in Settings" :
      "Check the target and show what would be created. Nothing is written.";
    var todo = v && (v.counts.create || v.counts.inst_create);
    var label = M.copyLabel();
    if (label) { ui.copy.textContent = label; ui.copy.className = "btn danger"; }
    M.enable(ui.copy, !!(v && ready && !M.busy && todo && v.status !== "running"));
    ui.reuse.disabled = ui.suffix.disabled = !!M.busy;
  };
})(window.MBC);
