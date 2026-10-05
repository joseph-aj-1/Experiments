/*
 * Mfg Item Viewer - ui: builds the widget layout (search bar, drop zone, status, details area)
 * and handles the collapsible item details. The dashboard may strip markup from the widget
 * body, so everything is created here at runtime. Styles: css/mfgitem-viewer.css.
 */
(function (M) {
  "use strict";
  var el = M.el;

  M.buildUi = function (root) {
    var ui = {};
    ui.wrap = el("div", "mfv");
    var bar = el("div", "bar");
    ui.q = el("input"); ui.q.type = "text"; ui.q.placeholder = "Title, name or physical ID (e.g. AJ MA 100)";
    ui.go = el("span", "go", "Search");               // spans styled as buttons: never stripped by the loader
    ui.go.setAttribute("role", "button"); ui.go.setAttribute("tabindex", "0"); ui.go.setAttribute("aria-disabled", "true");
    ui.pdf = el("span", "pdf", "Export PDF");
    ui.pdf.setAttribute("role", "button"); ui.pdf.setAttribute("tabindex", "0"); ui.pdf.setAttribute("aria-disabled", "true");
    ui.pdf.setAttribute("title", "Download a PDF of the displayed item (watermarked DRAFT), with its specifications attached");
    bar.appendChild(ui.q); bar.appendChild(ui.go); bar.appendChild(ui.pdf);
    ui.drop = el("div", "drop", "or drop a Manufacturing Item here");
    ui.ctx = el("div", "ctx");
    ui.status = el("div", "status", "Starting (v" + M.version + ")…");
    ui.results = el("div", "results");
    ui.details = el("div", "details");
    [bar, ui.drop, ui.ctx, ui.status, ui.results, ui.details].forEach(function (n) { ui.wrap.appendChild(n); });
    root.innerHTML = "";
    root.style.margin = "0"; root.style.padding = "0"; root.style.overflow = "hidden";
    root.appendChild(ui.wrap);
    M.ui = ui;
    return ui;
  };

  // ---------- collapsible details (choice remembered as a widget value) ----------
  var collapsedMem = false;
  M.detailsCollapsed = function () {
    try { var v = M.w.getValue && M.w.getValue("detailsCollapsed"); if (v != null) return v === true || v === "true"; } catch (ignored) { return collapsedMem; }
    return collapsedMem;
  };
  M.toggleDetails = function () {
    var c = !M.detailsCollapsed();
    collapsedMem = c;
    try { if (M.w.setValue) M.w.setValue("detailsCollapsed", c ? "true" : "false"); } catch (ignored) { /* not stored */ }
    var body = M.ui.details.querySelector(".dbody"), head = M.ui.details.querySelector(".dtoggle");
    if (body) body.style.display = c ? "none" : "";
    if (head) {
      head.setAttribute("aria-expanded", String(!c));
      var tg = head.querySelector(".tg"); if (tg) tg.textContent = c ? "Show details ▸" : "Hide details ▾";
    }
  };
})(window.MFV);
