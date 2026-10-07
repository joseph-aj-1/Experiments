/*
 * Route Viewer - groups: members of the user groups assigned to route tasks.
 * UsersGroup Web Services on the tenant's own "usersgroup" service (from the service
 * registry):  POST {usersgroup}/3drdfpersist/resources/v1/usersgroup/groups
 *             ?select=members  body {"groups":[{"uri":"uuid:<id>"}]}
 * Route tasks assigned to a group carry assigneeType "Group Proxy" and the group's id
 * in taskAssignee, which is the UsersGroup URI "uuid:<id>".
 * Members come back as e-mail addresses. Only groups the signed-in user may read are returned.
 */
(function (M) {
  "use strict";
  var PATH = "/3drdfpersist/resources/v1/usersgroup";
  var BATCH = 100, TOP_PERSONS = 200;
  var cache = {};          // uuid -> promise of { members: [...], error }

  M.isGroupTask = function (t) { return /group/i.test(t.assigneeType || ""); };
  M.groupUri = function (t) {
    var id = String(t.taskAssignee || t.taskAssigneeUsername || "");
    return id ? (id.indexOf("uuid:") === 0 ? id : "uuid:" + id) : "";
  };

  function viaGroupsList(uris) {
    var url = M.app.usersgroup + PATH + "/groups?select=members&top_persons=" + TOP_PERSONS;
    return M.request("POST", url, { groups: uris.map(function (u) { return { uri: u }; }) }, { ctx: false })
      .then(function (r) {
        var out = {};
        ((r && r.groups) || []).forEach(function (g) { out[g.uri] = { members: g.members || [] }; });
        ((r && (r.groups_failed || r.failed_groups || r.errors)) || []).forEach(function (f) {
          if (f && f.uri) out[f.uri] = { members: [], error: f.message || f.error || "not readable" };
        });
        return out;
      });
  }
  // fallback: list every group the user can read, with members, and pick ours
  function viaSearch(uris) {
    var url = M.app.usersgroup + PATH + "?select=members&top=100&top_persons=" + TOP_PERSONS;
    return M.request("GET", url, null, { ctx: false }).then(function (r) {
      var out = {};
      ((r && r.groups) || []).forEach(function (g) { if (uris.indexOf(g.uri) >= 0) out[g.uri] = { members: g.members || [] }; });
      return out;
    });
  }

  // uris -> promise of { uri: { members: [...], error? } }
  M.loadGroupMembers = function (uris) {
    var todo = uris.filter(function (u) { return u && !cache[u]; });
    var batches = [];
    for (var i = 0; i < todo.length; i += BATCH) batches.push(todo.slice(i, i + BATCH));
    batches.forEach(function (b) {
      var p = M.app.usersgroup ? viaGroupsList(b).catch(function (e1) {
        return viaSearch(b).catch(function () { throw e1; });
      }) : Promise.reject(new Error("The UsersGroup service is not available on this tenant."));
      b.forEach(function (u) {
        cache[u] = p.then(function (res) {
          return res[u] || { members: [], error: "group not found, or you are not allowed to read it" };
        }, function (e) { return { members: [], error: e.message }; });
      });
    });
    return Promise.all(uris.map(function (u) { return cache[u] || Promise.resolve({ members: [], error: "no group id" }); }))
      .then(function (list) { var out = {}; uris.forEach(function (u, k) { out[u] = list[k]; }); return out; });
  };
  M.clearGroupCache = function () { cache = {}; };
})(window.RTV);
