// Stand-in for the 3DDashboard runtime, replaying real dsrt / usersgroup responses from 2026-10-07.
(function () {
  var SPACE = "https://oi000629352-eu1-demo-space.3dexperience.3ds.com/enovia";
  var UG = "https://oi000629352-eu1-demo-usersgroup.3dexperience.3ds.com";
  function route(o) {
    var base = { type: "Route", revision: "1", isLatestRevision: "TRUE", routeBasePurpose: "Approval", AutoStopOnRejection: "Immediate",
      routeCompletionAction: "Promote Connected Object", owner: "hjh", ownerFullName: "Arun JOSEPH" };
    for (var k in o) base[k] = o[k];
    return base;
  }
  var R100 = route({ id: "82A2A5E1472F17006AC51846401AA54A", title: "R-OI000629352-0000100", name: "R-OI000629352-0000100",
    description: "Approval route generated from approvers to validate Change Action : CA-OI000629352-00000001, titled : AJ CA 100",
    state: "Complete", routeStatus: "Finished", attRestrictMembers: "All", activityState: "Approved",
    tasks: [{ id: "82A2A5E1472F17006AC51848401AA57A", type: "Inbox Task", allowDelegation: "FALSE", assigneeSetDueDate: "Yes", needsOwnerReview: "No",
      title: "Approval task to review changes done on Change Action : CA-OI000629352-00000001, titled : AJ CA 100", comments: "aaa", routeTaskPriority: "Medium",
      taskAction: "Approve", instructions: "Review changes done under Change Action : CA-OI000629352-00000001, titled : AJ CA 100 ", taskDueDate: "2026-10-07T15:49:53.000Z",
      approvalStatus: "Approve", name: "IT-OI000629352-0000100", current: "Complete", taskActualCompletionDate: "10/6/2026 3:50:03 PM", taskOrder: "1",
      assigneeTitle: "", assigneeType: "Person", taskAssignee: "Arun JOSEPH", taskAssigneeUsername: "hjh" }] });
  var R101 = route({ id: "82A2A5E1472F17006AC51AF4401AAB1E", title: "R-OI000629352-0000101", name: "R-OI000629352-0000101",
    description: "Approval route generated from approvers to validate Change Action : CA-OI000629352-00000002, titled : AJ CA 101",
    state: "In Process", routeStatus: "Started", attRestrictMembers: "Organization", activityState: "Awaiting Approval",
    tasks: [{ id: "82A2A5E1472F17006AC51AF5401AAB52", type: "Inbox Task", allowDelegation: "FALSE", assigneeSetDueDate: "Yes", needsOwnerReview: "No",
      title: "Approve", comments: "", routeTaskPriority: "Medium", taskAction: "Approve", instructions: "Approve the Task", taskDueDate: "2026-10-07T15:59:48.000Z",
      approvalStatus: "None", name: "IT-OI000629352-0000101", current: "Assigned", taskActualCompletionDate: "", taskOrder: "1", parallelNodeProcessionRule: "All",
      assigneeTitle: "Experimental Group", assigneeType: "Group Proxy", taskAssignee: "e6cd813b-c67d-42d9-8eac-232c23f4e6cc", taskAssigneeUsername: "e6cd813b-c67d-42d9-8eac-232c23f4e6cc" }] });
  // synthetic multi-task route: two groups (one unreadable), a person, a draft task, out-of-order tasks, HTML in a title
  var RX = route({ id: "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", title: "R-MULTI", name: "R-MULTI", description: "Synthetic route", state: "In Process",
    routeStatus: "Started", activityState: "Awaiting Approval",
    tasks: [
      { id: "T3", title: "Final sign-off", name: "IT-3", taskOrder: "3", current: "Draft", approvalStatus: "None", taskAction: "Approve", assigneeType: "Group Proxy",
        assigneeTitle: "Hidden Group", taskAssignee: "00000000-dead-beef-0000-000000000000", routeTaskPriority: "High", assigneeSetDueDate: "No" },
      { id: "T1", title: "<img src=x onerror=window.__xss=1>", name: "IT-1", taskOrder: "1", current: "Complete", approvalStatus: "Reject", taskAction: "Approve",
        assigneeType: "Person", taskAssignee: "Arun JOSEPH", taskAssigneeUsername: "hjh", routeTaskPriority: "Low", taskDueDate: "2026-10-01T10:00:00.000Z",
        taskActualCompletionDate: "10/2/2026 9:00:00 AM", comments: "Not ok" },
      { id: "T2", title: "Review", name: "IT-2", taskOrder: "2", current: "Assigned", approvalStatus: "None", taskAction: "Comment", assigneeType: "Group Proxy",
        assigneeTitle: "Experimental Group", taskAssignee: "e6cd813b-c67d-42d9-8eac-232c23f4e6cc", routeTaskPriority: "Medium", taskDueDate: "2099-01-01T10:00:00.000Z" },
      { id: "T2b", title: "Review again", name: "IT-2b", taskOrder: "2", current: "Assigned", approvalStatus: "None", taskAction: "Approve", assigneeType: "Group Proxy",
        assigneeTitle: "Experimental Group", taskAssignee: "e6cd813b-c67d-42d9-8eac-232c23f4e6cc", routeTaskPriority: "Medium", assigneeSetDueDate: "Yes" }
    ] });
  var ROUTES = {}; [R100, R101, RX].forEach(function (r) { ROUTES[r.id] = r; });
  var GROUPS = { "uuid:e6cd813b-c67d-42d9-8eac-232c23f4e6cc": { uri: "uuid:e6cd813b-c67d-42d9-8eac-232c23f4e6cc", title: "Experimental Group", members: ["arun.joseph@3ds.com"] } };
  window.__extraMember = function (m) { GROUPS["uuid:e6cd813b-c67d-42d9-8eac-232c23f4e6cc"].members.push(m); };
  window.__calls = []; window.__ugCalls = [];
  function strip(r) { var o = {}; for (var k in r) if (k !== "tasks") o[k] = r[k]; return o; }
  function respond(url, opts) {
    var u = new URL(url), h = opts.headers || {};
    if (u.host.indexOf("-usersgroup.") >= 0) {
      window.__ugCalls.push({ method: opts.method, path: u.pathname + u.search, ctx: h.SecurityContext || null, body: opts.data || null });
      if (window.__failUG) return [500, { message: "UsersGroup is down" }];
      if (u.pathname === "/3drdfpersist/resources/v1/usersgroup/groups" && opts.method === "POST") {
        if (u.searchParams.get("select") !== "members") return [400, { message: "select=members expected" }];
        var req = JSON.parse(opts.data).groups;
        return [200, { groups: req.map(function (g) { return GROUPS[g.uri]; }).filter(Boolean) }];
      }
      return [404, { message: "no ug route" }];
    }
    var p = u.pathname.replace("/enovia", "");
    window.__calls.push({ path: p + u.search, ctx: h.SecurityContext || null });
    if (u.searchParams.get("tenant") !== "OI000629352") return [403, { message: "tenant missing" }];
    if (p === "/resources/modeler/pno/person")
      return [200, { collabspaces: [{ name: "Common Space", couples: [{ organization: { name: "Company Name" }, role: { name: "VPLMProjectLeader" } }, { organization: { name: "Company Name" }, role: { name: "VPLMCreator" } }] }],
                     preferredcredentials: { collabspace: { name: "Common Space" }, role: { name: "VPLMProjectLeader" }, organization: { name: "Company Name" } } }];
    if (!h.SecurityContext) return [401, { message: "SecurityContext required" }];
    if (p === "/resources/v1/modeler/dsrt/routes/search") {
      if (u.searchParams.get("routeStateFilter") !== "Define,In Process,Complete") return [400, { message: "state filter" }];
      var q = (u.searchParams.get("searchStr") || "").toLowerCase();
      var hits = [R100, R101, RX].filter(function (r) { return (r.name + " " + r.description).toLowerCase().indexOf(q) >= 0; }).map(strip);
      return [200, { success: true, statusCode: 200, items: hits.length, data: hits }];
    }
    var m = p.match(/^\/resources\/v1\/modeler\/dsrt\/routes\/([0-9A-Za-z]+)$/);
    if (m) {
      if (!ROUTES[m[1]]) return [404, { success: false, message: "Object does not exist" }];
      var r = u.searchParams.get("$include") === "tasks" ? ROUTES[m[1]] : strip(ROUTES[m[1]]);
      return [200, { success: true, statusCode: 200, items: 1, data: [JSON.parse(JSON.stringify(r))] }];
    }
    return [404, { message: "no route " + p }];
  }
  var WAFData = { authenticatedRequest: function (url, opts) {
    setTimeout(function () { var r = respond(url, opts); if (r[0] === 200) opts.onComplete(r[1]); else opts.onFailure(new Error("HTTP " + r[0]), r[1]); }, 20);
  } };
  var Compass = { getServiceUrl: function (o) { setTimeout(function () {
    if (o.serviceName === "usersgroup") { if (window.__noUGRegistry) return o.onFailure && o.onFailure("unknown"); return o.onComplete([{ platformId: "OI000629352", url: UG }]); }
    o.onComplete(SPACE); }, 10); } };
  var dropHandlers = null;
  var DnD = { droppable: function (el, h) { dropHandlers = h; } };
  window.__drop = function (payload) { dropHandlers.drop(JSON.stringify(payload)); };
  var prefs = { x3dPlatformId: "OI000629352" }, events = {};
  window.__events = events;
  window.widget = { body: document.body, getValue: function (k) { return prefs[k]; }, setValue: function (k, v) { prefs[k] = v; },
    addPreference: function (p) { window.__pref = p; }, addEvent: function (n, f) { events[n] = f; },
    setTitle: function (t) { window.__title = t; } };
  window.define = function () {}; window.define.amd = {};
  window.require = function (deps, cb) {
    var map = { "DS/WAFData/WAFData": WAFData, "DS/i3DXCompassServices/i3DXCompassServices": Compass, "DS/DataDragAndDrop/DataDragAndDrop": DnD };
    setTimeout(function () { cb.apply(null, deps.map(function (d) { return map[d]; })); }, 0);
  };
})();
