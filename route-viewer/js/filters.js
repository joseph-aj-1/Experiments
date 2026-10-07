/*
 * Route Viewer - filters: column value filters for the task table (like the platform's
 * "Filter Column"): a funnel button in the Assignee and User Group Members headers, or
 * right-click a header -> Filter Column / Clear Filter / Clear All Filters.
 * The popup lists each distinct value with its task count, a refine box, select-all,
 * sort, "n of m selected", Reset / OK / Cancel. A task with several group members
 * matches when any of its members is selected. Filters stay while the same route is
 * refreshed and are cleared when another route is opened.
 */
(function (M) {
  "use strict";
  var esc = M.esc;
  var BLANK = "(Blank)";

  var COLS = {
    asg: { label: "Assignee", values: function (t) {
      if (M.isGroupTask(t)) return [t.assigneeTitle || t.taskAssignee || BLANK];
      return [t.taskAssignee || t.assigneeTitle || BLANK];
    } },
    mem: { label: "User Group Members", values: function (t) {
      if (!M.isGroupTask(t)) return [BLANK];
      var r = t._mem;
      if (!r) return ["(Loading…)"];
      if (r.error) return ["(Could not read members)"];
      return r.members.length ? r.members.slice() : ["(No members)"];
    } }
  };
  M.FILTER_COLS = COLS;

  var state = { routeId: null, sel: {} };   // sel[col] = { value: true } (only the selected values); absent = no filter
  var pop = null, menu = null;

  // called by route.js on every render
  M.filtersForRoute = function (routeId) {
    if (state.routeId !== routeId) { state.routeId = routeId; state.sel = {}; }
  };
  M.filterHeader = function (col) {
    return "<span class='fbtn' role='button' tabindex='0' data-col='" + col + "' title='Filter column'></span>";
  };

  function tasks() { return (M.app.view && M.app.view.tasks) || []; }

  // distinct values -> task counts
  function valueCounts(col) {
    var counts = {};
    tasks().forEach(function (t) {
      var seen = {};
      COLS[col].values(t).forEach(function (v) { if (!seen[v]) { seen[v] = 1; counts[v] = (counts[v] || 0) + 1; } });
    });
    return counts;
  }

  function matches(t) {
    return Object.keys(state.sel).every(function (col) {
      var s = state.sel[col];
      return COLS[col].values(t).some(function (v) { return s[v]; });
    });
  }

  M.applyFilters = function () {
    var route = M.ui && M.ui.route, list = tasks();
    if (!route) return;
    var shown = 0;
    list.forEach(function (t, k) {
      var tr = route.querySelector("tr[data-k='" + k + "']");
      var ok = matches(t);
      if (ok) shown++;
      if (tr) tr.style.display = ok ? "" : "none";
    });
    var active = Object.keys(state.sel);
    Array.prototype.forEach.call(route.querySelectorAll("table.tasks th[data-col]"), function (th) {
      var on = !!state.sel[th.getAttribute("data-col")];
      th.className = th.className.replace(/\s*\bfiltered\b/g, "") + (on ? " filtered" : "");
      var b = th.querySelector(".fbtn");
      if (b) b.setAttribute("title", on ? "Filtered — click to change" : "Filter column");
    });
    var sum = route.querySelector(".fsum");
    if (sum) {
      sum.innerHTML = active.length
        ? "Showing " + shown + " of " + list.length + " task" + (list.length === 1 ? "" : "s") + " — filtered on " +
          esc(active.map(function (c) { return COLS[c].label; }).join(", ")) +
          ". <span class='link fclear' role='button' tabindex='0'>Clear filters</span>"
        : "";
      sum.style.display = active.length ? "" : "none";
    }
  };

  function clearFilter(col) { if (col) delete state.sel[col]; else state.sel = {}; M.applyFilters(); }

  // ---------- popup ----------
  function closePopups() {
    if (pop) { pop.parentNode && pop.parentNode.removeChild(pop); pop = null; }
    if (menu) { menu.parentNode && menu.parentNode.removeChild(menu); menu = null; }
  }

  function place(box, th) {
    var wrap = M.ui.wrap, wr = wrap.getBoundingClientRect(), r = th.getBoundingClientRect();
    wrap.appendChild(box);
    var left = r.left - wr.left + wrap.scrollLeft, top = r.bottom - wr.top + wrap.scrollTop + 2;
    var maxLeft = wrap.scrollLeft + wrap.clientWidth - box.offsetWidth - 4;
    box.style.left = Math.max(wrap.scrollLeft + 4, Math.min(left, maxLeft)) + "px";
    box.style.top = top + "px";
  }

  function openFilter(col, th) {
    closePopups();
    var counts = valueCounts(col), values = Object.keys(counts);
    var cur = state.sel[col];
    var picked = {};
    values.forEach(function (v) { picked[v] = cur ? !!cur[v] : true; });
    var asc = true, refine = "";

    pop = M.el("div", "fpop");
    pop.setAttribute("role", "dialog"); pop.setAttribute("aria-label", "Filter " + COLS[col].label);
    pop.innerHTML =
      "<input type='text' class='frefine' placeholder='Type text to refine values' />" +
      "<div class='fhead'><input type='checkbox' class='fall' aria-label='Select all' /><span class='fvh'>Values</span>" +
        "<span class='fsort' role='button' tabindex='0' title='Sort'></span></div>" +
      "<div class='flist'></div>" +
      "<div class='fcount'></div>" +
      "<div class='ffoot'><span class='freset' role='button' tabindex='0'>Reset</span>" +
        "<span class='fok' role='button' tabindex='0'>OK</span><span class='fcancel' role='button' tabindex='0'>Cancel</span></div>";
    var input = pop.querySelector(".frefine"), list = pop.querySelector(".flist"), all = pop.querySelector(".fall"),
        count = pop.querySelector(".fcount"), ok = pop.querySelector(".fok"), sortBtn = pop.querySelector(".fsort");

    function visible() {
      var q = refine.toLowerCase();
      return values.filter(function (v) { return !q || v.toLowerCase().indexOf(q) >= 0; })
        .sort(function (a, b) { return (asc ? 1 : -1) * a.localeCompare(b, undefined, { sensitivity: "base" }); });
    }
    function draw() {
      var vis = visible();
      list.innerHTML = vis.length
        ? vis.map(function (v) {
            return "<label class='fval" + (picked[v] ? " on" : "") + "'><input type='checkbox' data-v='" + esc(v) + "'" + (picked[v] ? " checked" : "") +
              " /><span>" + esc(v) + " (" + counts[v] + ")</span></label>";
          }).join("")
        : "<div class='fnone'>No matching values</div>";
      counts_();
    }
    // counts, select-all state and OK, without rebuilding the list (keeps keyboard focus on a value)
    function counts_() {
      var vis = visible();
      var nSel = values.filter(function (v) { return picked[v]; }).length;
      var nVisSel = vis.filter(function (v) { return picked[v]; }).length;
      all.checked = vis.length > 0 && nVisSel === vis.length;
      all.indeterminate = nVisSel > 0 && nVisSel < vis.length;
      count.textContent = nSel + " of " + values.length + " selected";
      ok.setAttribute("aria-disabled", nSel ? "false" : "true");
      sortBtn.className = "fsort " + (asc ? "asc" : "desc");
      sortBtn.setAttribute("title", asc ? "Sorted A→Z (click for Z→A)" : "Sorted Z→A (click for A→Z)");
    }
    function apply() {
      if (ok.getAttribute("aria-disabled") === "true") return;
      var nSel = values.filter(function (v) { return picked[v]; }).length;
      if (nSel === values.length) delete state.sel[col];
      else { var s = {}; values.forEach(function (v) { if (picked[v]) s[v] = true; }); state.sel[col] = s; }
      closePopups(); M.applyFilters();
    }

    input.addEventListener("input", function () { refine = input.value; draw(); });
    all.addEventListener("change", function () { visible().forEach(function (v) { picked[v] = all.checked; }); draw(); });
    list.addEventListener("change", function (ev) {
      var v = ev.target.getAttribute("data-v");
      if (v != null) { picked[v] = ev.target.checked; ev.target.parentNode.className = "fval" + (picked[v] ? " on" : ""); counts_(); }
    });
    function act(cls, fn) {
      var b = pop.querySelector(cls);
      b.addEventListener("click", fn);
      b.addEventListener("keydown", function (ev) { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); fn(); } });
    }
    act(".fsort", function () { asc = !asc; draw(); });
    act(".freset", function () { values.forEach(function (v) { picked[v] = true; }); refine = ""; input.value = ""; draw(); });
    act(".fok", apply);
    act(".fcancel", closePopups);
    // Enter anywhere in the popup (refine box, a value) applies; Escape cancels
    pop.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") { ev.preventDefault(); closePopups(); }
      else if (ev.key === "Enter" && ev.target.getAttribute("role") !== "button") { ev.preventDefault(); apply(); }
    });
    pop.addEventListener("mousedown", function (ev) { ev.stopPropagation(); });

    draw();
    place(pop, th);
    input.focus();
  }

  // ---------- header context menu ----------
  function openMenu(col, th, x, y) {
    closePopups();
    menu = M.el("div", "fmenu");
    menu.setAttribute("role", "menu");
    var items = [["filter", "Filter Column", true], ["clear", "Clear Filter", !!state.sel[col]], ["clearall", "Clear All Filters", Object.keys(state.sel).length > 0]];
    menu.innerHTML = items.map(function (it) {
      return "<div class='fmi fmi-" + it[0] + "' role='menuitem' tabindex='-1' data-a='" + it[0] + "'" + (it[2] ? "" : " aria-disabled='true'") + ">" + it[1] + "</div>";
    }).join("");
    menu.addEventListener("mousedown", function (ev) { ev.stopPropagation(); });
    menu.addEventListener("click", function (ev) {
      var a = ev.target.getAttribute("data-a");
      if (!a || ev.target.getAttribute("aria-disabled") === "true") return;
      closePopups();
      if (a === "filter") openFilter(col, th);
      else if (a === "clear") clearFilter(col);
      else clearFilter(null);
    });
    var wrap = M.ui.wrap, wr = wrap.getBoundingClientRect();
    wrap.appendChild(menu);
    menu.style.left = Math.min(x - wr.left + wrap.scrollLeft, wrap.scrollLeft + wrap.clientWidth - menu.offsetWidth - 4) + "px";
    menu.style.top = (y - wr.top + wrap.scrollTop) + "px";
  }

  M.initFilters = function (ui) {
    ui.wrap.style.position = "relative";
    ui.route.addEventListener("click", function (ev) {
      var b = ev.target.closest ? ev.target.closest(".fbtn") : null;
      if (b) { ev.stopPropagation(); return openFilter(b.getAttribute("data-col"), b.parentNode); }
      if (ev.target.classList && ev.target.classList.contains("fclear")) clearFilter(null);
    });
    ui.route.addEventListener("keydown", function (ev) {
      if (ev.key !== "Enter" && ev.key !== " ") return;
      if (ev.target.classList.contains("fbtn")) { ev.preventDefault(); openFilter(ev.target.getAttribute("data-col"), ev.target.parentNode); }
      else if (ev.target.classList.contains("fclear")) { ev.preventDefault(); clearFilter(null); }
    });
    ui.route.addEventListener("contextmenu", function (ev) {
      var th = ev.target.closest ? ev.target.closest("table.tasks th[data-col]") : null;
      if (!th) return;
      ev.preventDefault();
      openMenu(th.getAttribute("data-col"), th, ev.clientX, ev.clientY);
    });
    document.addEventListener("mousedown", function (ev) {
      if ((pop && pop.contains(ev.target)) || (menu && menu.contains(ev.target))) return;
      closePopups();
    });
    document.addEventListener("keydown", function (ev) { if (ev.key === "Escape") closePopups(); });
  };
  M.closeFilterPopups = closePopups;
})(window.RTV);
