/*
 * Route Viewer - ui: builds the widget layout (search bar, drop zone, status, results,
 * route area). The dashboard may strip markup from the widget body, so everything is
 * created here at runtime. Styles: css/route-viewer.css.
 */
(function (M) {
  "use strict";
  var el = M.el;

  M.buildUi = function (root) {
    var ui = {};
    ui.wrap = el("div", "rtv");
    var bar = el("div", "bar");
    ui.q = el("input"); ui.q.type = "text"; ui.q.placeholder = "Route name, title or keyword (e.g. R-OI000629352-0000101 or CA-…)";
    ui.go = el("span", "go", "Search");            // spans styled as buttons: never stripped by the loader
    ui.go.setAttribute("role", "button"); ui.go.setAttribute("tabindex", "0"); ui.go.setAttribute("aria-disabled", "true");
    ui.refresh = el("span", "ghost", "Refresh");
    ui.refresh.setAttribute("role", "button"); ui.refresh.setAttribute("tabindex", "0"); ui.refresh.setAttribute("aria-disabled", "true");
    ui.refresh.setAttribute("title", "Reload the displayed route and its user groups");
    bar.appendChild(ui.q); bar.appendChild(ui.go); bar.appendChild(ui.refresh);
    ui.drop = el("div", "drop", "or drop a Route (or a Change Action / object with a route) here");
    ui.ctx = el("div", "ctx");
    ui.status = el("div", "status", "Starting (v" + M.version + ")…");
    ui.results = el("div", "results");
    ui.route = el("div", "route");
    [bar, ui.drop, ui.ctx, ui.status, ui.results, ui.route].forEach(function (n) { ui.wrap.appendChild(n); });
    root.innerHTML = "";
    root.style.margin = "0"; root.style.padding = "0"; root.style.overflow = "hidden";
    root.appendChild(ui.wrap);
    M.ui = ui;
    return ui;
  };
})(window.RTV);
