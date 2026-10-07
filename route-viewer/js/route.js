/*
 * Route Viewer - route: search, route header and the task table (Routes Web Services, dsrt).
 *   GET {3DSpace}/resources/v1/modeler/dsrt/routes/search?searchStr=..&routeStateFilter=..&$top=..
 *   GET {3DSpace}/resources/v1/modeler/dsrt/routes/{id}?$include=tasks
 * Group-assigned tasks get their members from groups.js.
 */
(function (M) {
  "use strict";
  var esc = M.esc, RT = "/resources/v1/modeler/dsrt/routes";
  var STATES = "Define,In Process,Complete";

  // task "current" -> label + badge colour (as shown in the platform's Approvals tab)
  var TASK_STATE = { Assigned: ["To Do", "todo"], Review: ["In Review", "review"], Complete: ["Complete", "done"],
                     Draft: ["Draft", "draft"], Inactive: ["Draft", "draft"] };
  var ROUTE_STATE = { Define: "define", "In Process": "process", Complete: "done", Archive: "draft" };

  function looksLikePhysicalId(s) { return /^[0-9A-F]{32}$/i.test(s); }

  M.search = function (text, label) {
    var ui = M.ui;
    if (!M.ready) return;
    text = (text || "").trim();
    if (!text) return;
    ui.route.innerHTML = ""; ui.results.innerHTML = "";
    M.app.view = null; ui.refresh.setAttribute("aria-disabled", "true");
    if (looksLikePhysicalId(text)) return M.show(text);
    M.setStatus("Searching routes…");
    return M.get(RT + "/search?searchStr=" + encodeURIComponent(text) + "&routeStateFilter=" + encodeURIComponent(STATES) + "&$top=25")
      .then(function (resp) {
        var items = M.data(resp);
        if (!items.length) { M.setStatus("No routes match “" + (label || text) + "”. New routes can take a minute to appear in search."); return; }
        if (items.length === 1) return M.show(items[0].id);
        M.setStatus(items.length + " routes match — pick one.");
        ui.results.innerHTML = "<table class='list'><thead><tr><th>Name</th><th>State</th><th>Status</th><th>Purpose</th><th>Owner</th><th>Description</th></tr></thead><tbody>" +
          items.map(function (r) {
            return "<tr class='pick' data-id='" + esc(r.id) + "'><td>" + esc(r.name) + "</td><td>" + stateBadge(r.state) + "</td><td>" + esc(r.routeStatus) +
              "</td><td>" + esc(r.routeBasePurpose) + "</td><td>" + esc(r.ownerFullName || r.owner) + "</td><td class='desc'>" + esc(r.description) + "</td></tr>";
          }).join("") + "</tbody></table>";
      })
      .catch(function (e) { M.setStatus(e.message, true); });
  };

  function stateBadge(state) {
    return "<span class='badge rs-" + (ROUTE_STATE[state] || "other") + "'>" + esc(state || "") + "</span>";
  }

  M.show = function (id) {
    var seq = ++M.loadSeq;
    M.setStatus("Loading route…");
    M.ui.results.innerHTML = "";
    return M.get(RT + "/" + encodeURIComponent(id) + "?$include=tasks")
      .then(function (resp) {
        var route = M.data(resp)[0];
        if (!route) throw new Error("Route " + id + " was not found (or you can't see it in this context).");
        if (seq !== M.loadSeq) return;
        render(route);
        M.setStatus("");
        return loadMembers(route, seq);
      })
      .catch(function (e) { if (seq === M.loadSeq) M.setStatus(e.message, true); });
  };

  function order(t) { var n = parseInt(t.taskOrder, 10); return isNaN(n) ? 9999 : n; }

  function approval(t) {
    var a = t.approvalStatus || "";
    if (a === "Approve") return ["Approved", "ok"];
    if (a === "Reject") return ["Rejected", "bad"];
    if (a === "Abstain") return ["Abstained", ""];
    if (t.current === "Assigned" || t.current === "Review") return [t.taskAction === "Approve" ? "Awaiting Approval" : "In progress", ""];
    if (t.current === "Complete") return ["Completed", "ok"];
    return [t.taskAction === "Approve" ? "To be approved" : "Not started", "muted"];
  }

  function dueCell(t) {
    if (t.taskDueDate) {
      var d = new Date(t.taskDueDate), late = t.current !== "Complete" && !isNaN(d.getTime()) && d.getTime() < Date.now();
      return "<span class='clock" + (late ? " late" : "") + "' title='" + (late ? "Overdue" : "Due date") + "'>&#9719;</span>" + esc(M.fmtDate(t.taskDueDate));
    }
    return t.assigneeSetDueDate === "Yes" ? "<span class='muted'>Assignee-Set Due Date</span>" : "<span class='muted'>—</span>";
  }

  function assigneeCell(t) {
    if (M.isGroupTask(t)) {
      return "<span class='ico grp' title='User group'></span><span class='link'>" + esc(t.assigneeTitle || t.taskAssignee) + "</span>";
    }
    var name = t.taskAssignee || t.assigneeTitle || "";
    if (!name) return "<span class='muted'>Unassigned</span>";
    return "<span class='ico usr' title='Person'></span><span class='link'>" + esc(name) + "</span>" +
           (t.taskAssigneeUsername && t.taskAssigneeUsername !== name ? " <span class='muted'>(" + esc(t.taskAssigneeUsername) + ")</span>" : "");
  }

  function render(r) {
    var tasks = (r.tasks || []).slice().sort(function (a, b) { return order(a) - order(b) || String(a.title).localeCompare(String(b.title)); });
    var groups = tasks.filter(M.isGroupTask);
    M.app.view = { route: r, tasks: tasks };
    M.ui.refresh.setAttribute("aria-disabled", "false");
    var facts = [
      ["Name", r.name], ["Status", r.routeStatus], ["Activity", r.activityState], ["Purpose", r.routeBasePurpose],
      ["On completion", r.routeCompletionAction], ["Stop on rejection", r.AutoStopOnRejection], ["Restrict members", r.attRestrictMembers],
      ["Owner", (r.ownerFullName || "") + (r.owner ? " (" + r.owner + ")" : "")], ["Revision", r.revision]
    ].filter(function (f) { return f[1]; });
    var rows = tasks.map(function (t, k) {
      var st = TASK_STATE[t.current] || [t.current || "", "other"], ap = approval(t);
      return "<tr data-k='" + k + "'>" +
        "<td class='ord'>" + esc(t.taskOrder) + "</td>" +
        "<td class='ttl'><span class='ico task'></span><span title='" + esc(t.instructions || "") + "'>" + esc(t.title) + "</span>" +
          (t.name ? "<div class='sub'>" + esc(t.name) + "</div>" : "") + "</td>" +
        "<td>" + esc(t.taskAction) + "</td>" +
        "<td><span class='badge ts-" + st[1] + "'>" + esc(st[0]) + "</span></td>" +
        "<td class='ap " + ap[1] + "'>" + esc(ap[0]) + "</td>" +
        "<td class='asg'>" + assigneeCell(t) + "</td>" +
        "<td class='mem'>" + (M.isGroupTask(t) ? "<span class='muted'>Loading members…</span>" : "<span class='muted'>—</span>") + "</td>" +
        "<td class='due'>" + dueCell(t) + "</td>" +
        "<td><span class='prio p-" + esc(String(t.routeTaskPriority || "").toLowerCase()) + "'></span>" + esc(t.routeTaskPriority) + "</td>" +
        "<td>" + esc(t.taskActualCompletionDate ? M.fmtDate(t.taskActualCompletionDate, true) : "") + "</td>" +
        "<td class='cmt'>" + esc(t.comments) + "</td></tr>";
    }).join("");
    M.ui.route.innerHTML =
      "<div class='head'><div class='rico'></div><div class='hmain'>" +
        "<div class='title'>" + esc(r.title || r.name) + " " + stateBadge(r.state) + "</div>" +
        (r.description ? "<div class='rdesc'>" + esc(r.description) + "</div>" : "") +
        "<dl class='facts'>" + facts.map(function (f) { return "<dt>" + esc(f[0]) + "</dt><dd>" + esc(f[1]) + "</dd>"; }).join("") + "</dl>" +
      "</div></div>" +
      "<h3>Tasks — " + tasks.length + " task" + (tasks.length === 1 ? "" : "s") +
        (groups.length ? ", " + groups.length + " assigned to " + (groups.length === 1 ? "a user group" : "user groups") : "") + "</h3>" +
      "<div class='sub memsum'>" + (groups.length ? "Looking up user group members…" : "No task is assigned to a user group.") + "</div>" +
      "<div class='sub fsum' style='display:none'></div>" +
      (tasks.length ?
        "<div class='tblwrap'><table class='tasks'><thead><tr><th>Order</th><th>Title</th><th>Expected Action</th><th>Maturity State</th>" +
        "<th>Approval Status</th><th class='fcol' data-col='asg'>Assignee" + M.filterHeader("asg") + "</th>" +
        "<th class='mh fcol' data-col='mem'>User Group Members" + M.filterHeader("mem") + "</th><th>Due Date</th><th>Priority</th>" +
        "<th>Completed</th><th>Comments</th></tr></thead><tbody>" + rows + "</tbody></table></div>"
        : "<p class='empty'>This route has no tasks.</p>");
    if (M.closeFilterPopups) M.closeFilterPopups();
    M.filtersForRoute(r.id);
    M.applyFilters();
    if (M.w.setTitle) M.w.setTitle("Route: " + (r.title || r.name));
  }

  function loadMembers(r, seq) {
    var tasks = M.app.view.tasks;
    var uris = [];
    tasks.forEach(function (t) { if (M.isGroupTask(t)) { var u = M.groupUri(t); if (u && uris.indexOf(u) < 0) uris.push(u); } });
    if (!uris.length) return Promise.resolve();
    return M.loadGroupMembers(uris).then(function (byUri) {
      if (seq !== M.loadSeq) return;
      var all = {}, failed = 0, badGroups = {};
      tasks.forEach(function (t, k) {
        if (!M.isGroupTask(t)) return;
        var res = byUri[M.groupUri(t)] || { members: [], error: "no group id" };
        t._mem = res;
        var cell = M.ui.route.querySelector("tr[data-k='" + k + "'] td.mem");
        if (!cell) return;
        if (res.error) { failed++; badGroups[M.groupUri(t)] = true; cell.innerHTML = "<span class='err' title='" + esc(res.error) + "'>Could not read members: " + esc(res.error) + "</span>"; return; }
        res.members.forEach(function (m) { all[m] = true; });
        cell.innerHTML = res.members.length
          ? "<div class='cnt'>" + res.members.length + " member" + (res.members.length === 1 ? "" : "s") + "</div>" +
            res.members.map(function (m) { return "<div class='person'><a href='mailto:" + esc(m) + "'>" + esc(m) + "</a></div>"; }).join("")
          : "<span class='muted'>No members</span>";
      });
      M.applyFilters();
      var sum = M.ui.route.querySelector(".memsum");
      if (sum) {
        sum.textContent = uris.length + " user group" + (uris.length === 1 ? "" : "s") + ", " + Object.keys(all).length + " distinct member" +
          (Object.keys(all).length === 1 ? "" : "s") + (failed ? " (" + failed + " task" + (failed === 1 ? "" : "s") + " could not be resolved)" : "");
        sum.className = "sub memsum" + (Object.keys(badGroups).length === uris.length ? " error" : "");
      }
    });
  }
})(window.RTV);
