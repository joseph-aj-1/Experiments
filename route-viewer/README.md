# Route Viewer (3DDashboard widget)

Shows a Route and **all of its tasks**: order, title / task name, instructions (wrapped), expected action, maturity state,
approval status, assignee, **User Group Members** (for tasks assigned to a user group), due date,
priority, completion date and comments.

## Add it to a dashboard

* **Run Your App** widget → URL `https://joseph-aj-1.github.io/Experiments/route-viewer/index.html`, or
* upload `index.html` as-is (it is only a small loader; the app is loaded from GitHub Pages).

GitHub Pages must be enabled for `joseph-aj-1/Experiments` (Settings → Pages → `main` / root).
`manifest.json` is fetched without cache, so bump its `version` after a push to refresh the CSS/JS.

## Use

* Type a route name, title or keyword (e.g. `R-OI000629352-0000101`, or a Change Action name such as
  `CA-OI000629352-00000002`) and press **Search** / Enter. One match opens directly; several give a pick list.
  A 32-character physical ID opens that route directly.
* Or drop a **Route** (opens it) or another object, e.g. a **Change Action** (searches routes that mention it).
* **Filter** the Assignee and User Group Members columns: click the funnel in the header (or right-click
  the header → Filter Column / Clear Filter / Clear All Filters). Pick values (with task counts), refine by
  typing, sort, then OK. A task matches the member filter when any of its group members is selected;
  filters on both columns combine. Filters stay on Refresh and reset when another route is opened.
* **Refresh** (or the dashboard's refresh) reloads the route and re-reads group members.
* The security context comes from your preferred credentials; change it in the widget preferences.

## Web services used (signed-in user's session, via WAFData)

| What | Call |
|---|---|
| Security context | `GET {3DSpace}/resources/modeler/pno/person?current=true&select=collabspaces&select=preferredcredentials` |
| Route search | `GET {3DSpace}/resources/v1/modeler/dsrt/routes/search?searchStr=…&routeStateFilter=Define,In Process,Complete&$top=25` |
| Route + tasks | `GET {3DSpace}/resources/v1/modeler/dsrt/routes/{id}?$include=tasks` |
| Group members | `POST {usersgroup}/3drdfpersist/resources/v1/usersgroup/groups?select=members` body `{"groups":[{"uri":"uuid:<id>"}]}` (fallback: `GET …/usersgroup?select=members`) |

A task assigned to a group has `assigneeType: "Group Proxy"`, `assigneeTitle` = group title and
`taskAssignee` = the group UUID (UsersGroup URI `uuid:<UUID>`). Members are returned as e-mail
addresses; only groups the signed-in user may read are returned (others show an error in their cell).
The `usersgroup` URL comes from the service registry (fallback: `-space.` → `-usersgroup.`).

## Files

`index.html` (loader) · `manifest.json` · `css/route-viewer.css` · `js/core.js` (helpers, requests, context) ·
`js/ui.js` · `js/groups.js` (UsersGroup) · `js/filters.js` (column filters) · `js/route.js` (search, header, task table) · `js/main.js` (startup, events, drop)

## Test

`cd test && python run_test.py` — Playwright + `mock_platform.js` (real responses for R-…0100 / R-…0101
plus a synthetic multi-task route). Serves this folder in place of GitHub Pages.
