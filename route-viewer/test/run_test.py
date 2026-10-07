"""Headless test of the Route Viewer against a mocked 3DDashboard (mock_platform.js).
GitHub Pages URLs are served from the local route-viewer folder.  Run: python run_test.py"""
import os, json, pathlib
HERE = pathlib.Path(__file__).resolve().parent
os.chdir(HERE)
from playwright.sync_api import sync_playwright
APP = HERE.parent
PAGES = "https://joseph-aj-1.github.io/Experiments/route-viewer/"
html = open(APP / "index.html", encoding="utf-8").read()
mock = open("mock_platform.js", encoding="utf-8").read()
page_html = html.replace("\n<body>", "\n<body><script>" + mock + "</script>", 1)
assert mock in page_html
open("harness.html", "w", encoding="utf-8").write(page_html)
fails = []
def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: fails.append(msg)
R100, R101, RX = "82A2A5E1472F17006AC51846401AA54A", "82A2A5E1472F17006AC51AF4401AAB1E", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1300, "height": 700})
    hits = []
    def pages(route):
        path = route.request.url.split(PAGES, 1)[-1].split("?", 1)[0]
        hits.append(path)
        f_ = APP / path
        if not f_.is_file(): return route.fulfill(status=404, body="not found")
        ct = {"js": "application/javascript", "css": "text/css", "json": "application/json"}.get(f_.suffix[1:], "text/plain")
        route.fulfill(status=200, body=f_.read_bytes(), headers={"Access-Control-Allow-Origin": "*", "Content-Type": ct})
    ctx.route(PAGES + "**", pages)
    pg = ctx.new_page()
    errors = []; pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto((HERE / "harness.html").as_uri())
    pg.wait_for_function("document.querySelector('.status') && document.querySelector('.status').textContent.indexOf('Ready') === 0", timeout=5000)
    man = json.loads((APP / "manifest.json").read_text())
    check(hits[0] == "manifest.json" and [h for h in hits if h.startswith("js/")] == man["js"] and "css/route-viewer.css" in hits,
          "index.html loads manifest.json, the CSS and every script in manifest order")
    check(pg.evaluate("getComputedStyle(document.querySelector('.go')).backgroundColor") == "rgb(0, 86, 134)", "stylesheet applied")
    check(pg.inner_text(".ctx") == "Context: VPLMProjectLeader.Company Name.Common Space", "security context from preferred credentials")
    check(pg.evaluate("window.__pref && window.__pref.options.length") == 2, "context preference offered")
    def wait_members():
        pg.wait_for_function("document.querySelector('.memsum') && document.querySelector('.memsum').textContent.indexOf('Looking up') < 0", timeout=5000)
    # 1) exact name -> one hit -> route with a group task
    pg.fill(".rtv input", "R-OI000629352-0000101"); pg.click(".go")
    pg.wait_for_selector(".title"); wait_members()
    check("R-OI000629352-0000101" in pg.inner_text(".title") and pg.inner_text(".title .badge") == "In Process", "route title + state badge")
    facts = pg.inner_text(".facts")
    check(all(s in facts for s in ["Started", "Awaiting Approval", "Approval", "Promote Connected Object", "Immediate", "Organization", "Arun JOSEPH (hjh)"]), "route facts shown")
    check("CA-OI000629352-00000002" in pg.inner_text(".rdesc"), "route description shown")
    heads = pg.evaluate("Array.from(document.querySelectorAll('table.tasks thead th')).map(function(h){return h.textContent})")
    check(heads == ["Order", "Title", "Expected Action", "Maturity State", "Approval Status", "Assignee", "User Group Members", "Due Date", "Priority", "Completed", "Comments"], "task table columns")
    cells = pg.evaluate("Array.from(document.querySelectorAll('table.tasks tbody tr')[0].cells).map(function(c){return c.innerText.trim()})")
    check(cells[1].startswith("Approve") and "IT-OI000629352-0000101" in cells[1] and cells[2] == "Approve" and cells[3] == "To Do" and cells[4] == "Awaiting Approval",
          "task row: title, task name, action, To Do, Awaiting Approval (%s)" % cells[:5])
    check(cells[5] == "Experimental Group" and pg.locator("table.tasks td.asg .ico.grp").count() == 1, "assignee is the group, with group icon")
    check(cells[6] == "1 member\narun.joseph@3ds.com" and pg.get_attribute("td.mem a", "href") == "mailto:arun.joseph@3ds.com", "User Group Members lists the group's members (mailto)")
    check("Medium" in cells[8] and cells[9] == "", "priority / completed")
    check("1 user group, 1 distinct member" in pg.inner_text(".memsum"), "member summary")
    ug = pg.evaluate("window.__ugCalls")
    check(len(ug) == 1 and ug[0]["method"] == "POST" and "/3drdfpersist/resources/v1/usersgroup/groups?select=members" in ug[0]["path"]
          and json.loads(ug[0]["body"]) == {"groups": [{"uri": "uuid:e6cd813b-c67d-42d9-8eac-232c23f4e6cc"}]} and ug[0]["ctx"] is None,
          "one UsersGroup POST /groups with the uuid: URI and no SecurityContext")
    check(pg.get_attribute("td.ttl span[title]", "title") == "Approve the Task", "instructions as title tooltip")
    check(pg.evaluate("window.__title") == "Route: R-OI000629352-0000101", "widget title set")
    pg.screenshot(path="shot_r101.png", full_page=True)
    # 2) refresh picks up changed members (cache cleared)
    pg.evaluate("window.__extraMember('kristi.jensen@example.com')")
    pg.click(".ghost"); pg.wait_for_function("document.querySelector('td.mem') && document.querySelector('td.mem').textContent.indexOf('2 members') === 0", timeout=5000)
    check("kristi.jensen@example.com" in pg.inner_text("td.mem") and len(pg.evaluate("window.__ugCalls")) == 2, "Refresh reloads route and group members")
    pg.evaluate("window.__events.onRefresh()")
    pg.wait_for_function("window.__ugCalls.length === 3", timeout=5000)
    check(True, "dashboard onRefresh reloads too")
    # 3) person-assigned, completed route
    pg.fill(".rtv input", "R-OI000629352-0000100"); pg.click(".go")
    pg.wait_for_function("document.querySelector('.title') && document.querySelector('.title').textContent.indexOf('0000100') >= 0"); pg.wait_for_timeout(200)
    c2 = pg.evaluate("Array.from(document.querySelectorAll('table.tasks tbody tr')[0].cells).map(function(c){return c.innerText.trim()})")
    check(c2[3] == "Complete" and c2[4] == "Approved" and c2[5] == "Arun JOSEPH (hjh)" and c2[6] == "—" and c2[10] == "aaa" and "2026" in c2[9],
          "person task: Complete / Approved / person / no members / comments / completion date (%s)" % c2)
    check(pg.inner_text(".memsum") == "No task is assigned to a user group." and len(pg.evaluate("window.__ugCalls")) == 3, "no UsersGroup call for person-only route")
    check(pg.locator(".clock.late").count() == 0, "completed task is never shown as late")
    # 4) multi-hit search -> pick list
    pg.fill(".rtv input", "R-OI000629352"); pg.click(".go"); pg.wait_for_selector(".results tr.pick")
    check(pg.locator(".results tr.pick").count() == 2 and "2 routes match" in pg.inner_text(".status"), "pick list for several matches")
    pg.locator(".results tr.pick").nth(1).click(); pg.wait_for_selector(".title")
    check(pg.locator(".results tr").count() == 0 and "0000101" in pg.inner_text(".title"), "picking opens the route")
    # 5) synthetic route: sort, failures, escaping
    pg.fill(".rtv input", RX); pg.click(".go"); pg.wait_for_selector(".title"); wait_members()
    rows = pg.evaluate("Array.from(document.querySelectorAll('table.tasks tbody tr')).map(function(r){return Array.from(r.cells).map(function(c){return c.innerText.trim()})})")
    check([r_[0] for r_ in rows] == ["1", "2", "2", "3"] and rows[1][1].startswith("Review\n") and rows[2][1].startswith("Review again"), "tasks sorted by order, then title")
    check(pg.evaluate("window.__xss") is None and "<img" in rows[0][1], "HTML in task titles is escaped")
    check(rows[0][4] == "Rejected" and rows[0][3] == "Complete" and rows[3][3] == "Draft" and rows[3][4] == "To be approved" and rows[1][4] == "In progress",
          "approval labels: Rejected / To be approved / In progress")
    check("arun.joseph@3ds.com" in rows[1][6] and "arun.joseph@3ds.com" in rows[2][6] and "Could not read members" in rows[3][6], "unreadable group shows an error in its cell")
    check("2 user groups, 2 distinct members (1 task could not be resolved)" in pg.inner_text(".memsum"), "summary counts groups, members and failures")
    ug = pg.evaluate("window.__ugCalls")
    check(json.loads(ug[-1]["body"])["groups"] == [{"uri": "uuid:00000000-dead-beef-0000-000000000000"}], "already-known group comes from the cache; only the new group is fetched")
    check(rows[2][7] == "Assignee-Set Due Date" and pg.locator(".clock.late").count() == 0 and pg.locator(".clock").count() == 2, "due-date variants")
    check("4 tasks, 3 assigned to user groups" in pg.inner_text("h3").lower(), "heading counts tasks and group tasks")
    pg.screenshot(path="shot_multi.png", full_page=True)
    # 5b) column filters (Assignee, User Group Members)
    def select_none():
        if not pg.is_checked(".fpop .fall"): pg.click(".fpop .fall")
        pg.click(".fpop .fall")
    VIS = "Array.from(document.querySelectorAll('table.tasks tbody tr')).filter(function(r){return r.style.display !== 'none'}).map(function(r){return r.cells[1].innerText.split('\\n')[0]})"
    VALS = "Array.from(document.querySelectorAll('.fpop .fval')).map(function(l){return l.innerText.trim()})"
    check(pg.locator("th[data-col='asg'] .fbtn").count() == 1 and pg.locator("th[data-col='mem'] .fbtn").count() == 1 and pg.locator("th .fbtn").count() == 2,
          "filter buttons only on Assignee and User Group Members headers")
    pg.click("th[data-col='asg'] .fbtn"); pg.wait_for_selector(".fpop")
    check(pg.evaluate(VALS) == ["Arun JOSEPH (1)", "Experimental Group (2)", "Hidden Group (1)"] and pg.inner_text(".fpop .fcount") == "3 of 3 selected"
          and pg.is_checked(".fpop .fall"), "Assignee filter lists distinct values with task counts, all selected")
    check(pg.evaluate("document.activeElement.className") == "frefine", "refine box focused")
    pg.fill(".fpop .frefine", "exp")
    check(pg.evaluate(VALS) == ["Experimental Group (2)"], "typing refines the value list")
    pg.fill(".fpop .frefine", "")
    pg.click(".fpop .fall")
    check(pg.inner_text(".fpop .fcount") == "0 of 3 selected" and pg.get_attribute(".fpop .fok", "aria-disabled") == "true", "unselect all; OK disabled with nothing selected")
    pg.locator(".fpop .fval", has_text="Experimental Group").click()
    check(pg.evaluate("document.querySelector('.fpop .fall').indeterminate") and pg.inner_text(".fpop .fcount") == "1 of 3 selected", "select-all box shows partial selection")
    pg.click(".fpop .fok")
    check(pg.locator(".fpop").count() == 0 and pg.evaluate(VIS) == ["Review", "Review again"], "OK filters rows to the chosen assignee")
    check("filtered" in pg.get_attribute("th[data-col='asg']", "class") and "Showing 2 of 4 tasks — filtered on Assignee" in pg.inner_text(".fsum"), "header marked filtered; summary line")
    pg.click("th[data-col='mem'] .fbtn"); pg.wait_for_selector(".fpop")
    mv = pg.evaluate(VALS)
    check(mv == ["(Blank) (1)", "(Could not read members) (1)", "arun.joseph@3ds.com (2)", "kristi.jensen@example.com (2)"], "member filter lists every member, blanks and failures (%s)" % mv)
    pg.click(".fpop .fsort")
    check(pg.evaluate(VALS)[0] == "kristi.jensen@example.com (2)", "sort toggles Z→A")
    select_none(); pg.locator(".fpop .fval", has_text="(Could not read members)").click(); pg.click(".fpop .fok")
    check(pg.evaluate(VIS) == [], "filters combine (AND) — no task matches both")
    check("filtered on Assignee, User Group Members" in pg.inner_text(".fsum"), "summary names both filtered columns")
    pg.click("th[data-col='asg'] .fbtn"); pg.click(".fpop .freset"); pg.click(".fpop .fok")
    check(pg.evaluate(VIS) == ["Final sign-off"] and "filtered" not in pg.get_attribute("th[data-col='asg']", "class"), "Reset + OK removes the Assignee filter")
    pg.click("th[data-col='mem'] .fbtn"); select_none(); pg.locator(".fpop .fval", has_text="kristi").click(); pg.click(".fpop .fok")
    check(pg.evaluate(VIS) == ["Review", "Review again"], "a task matches when any of its group members is selected")
    pg.screenshot(path="shot_filtered.png", full_page=True)
    pg.click("th[data-col='asg'] .fbtn"); select_none(); pg.click(".fpop .fcancel")
    check(pg.locator(".fpop").count() == 0 and pg.evaluate(VIS) == ["Review", "Review again"], "Cancel leaves the filter unchanged")
    pg.click("th[data-col='asg'] .fbtn"); pg.keyboard.press("Escape")
    check(pg.locator(".fpop").count() == 0, "Escape closes the popup")
    pg.click("th[data-col='asg'] .fbtn"); pg.mouse.click(5, 650)
    check(pg.locator(".fpop").count() == 0, "clicking outside closes the popup")
    pg.click("th[data-col='mem']", button="right"); pg.wait_for_selector(".fmenu")
    items = pg.evaluate("Array.from(document.querySelectorAll('.fmenu .fmi')).map(function(i){return [i.textContent, i.getAttribute('aria-disabled')]})")
    check(items == [["Filter Column", None], ["Clear Filter", None], ["Clear All Filters", None]], "right-click header shows Filter Column / Clear Filter / Clear All Filters")
    pg.click(".fmenu .fmi-clear")
    check(len(pg.evaluate(VIS)) == 4 and not pg.is_visible(".fsum"), "Clear Filter shows every task again")
    pg.click("th[data-col='asg']", button="right"); pg.click(".fmenu .fmi-filter"); pg.wait_for_selector(".fpop")
    check(pg.locator(".fmenu").count() == 0, "Filter Column from the menu opens the value popup")
    select_none(); pg.locator(".fpop .fval", has_text="Hidden Group").click(); pg.keyboard.press("Enter")
    check(pg.evaluate(VIS) == ["Final sign-off"], "Enter in the popup applies")
    pg.click(".ghost"); wait_members(); pg.wait_for_timeout(300)
    check(pg.evaluate(VIS) == ["Final sign-off"] and "filtered" in pg.get_attribute("th[data-col='asg']", "class"), "filter kept when the same route is refreshed")
    pg.focus("th[data-col='mem'] .fbtn"); pg.keyboard.press("Enter")
    check(pg.locator(".fpop").count() == 1, "filter button works from the keyboard"); pg.keyboard.press("Escape")
    # 6) UsersGroup down
    pg.evaluate("window.__failUG = true"); pg.click(".ghost")
    pg.wait_for_function("document.querySelectorAll('td.mem .err').length === 3", timeout=5000)
    ugc = pg.evaluate("window.__ugCalls")[-2:]
    check(ugc[0]["method"] == "POST" and len(json.loads(ugc[0]["body"])["groups"]) == 2 and ugc[1]["method"] == "GET" and "select=members" in ugc[1]["path"],
          "Refresh fetches both groups in one POST; on failure it falls back to the group search")
    check(pg.locator("td.mem .err").count() == 3 and "UsersGroup is down" in pg.inner_text("td.mem .err >> nth=0") and "error" in pg.get_attribute(".memsum", "class"),
          "UsersGroup failure is reported per task and the route still shows")
    pg.evaluate("window.__failUG = false")
    # 7) drop a Route / a Change Action
    pg.evaluate("window.__drop({protocol:'3DXContent',data:{items:[{objectId:'%s',displayName:'R-OI000629352-0000101',objectType:'Route'}]}})" % R101)
    pg.wait_for_function("document.querySelector('.title') && document.querySelector('.title').textContent.indexOf('0000101') >= 0")
    check(any(c["path"].startswith("/resources/v1/modeler/dsrt/routes/" + R101) for c in pg.evaluate("window.__calls")), "dropped Route opens directly")
    check(pg.locator("th.filtered").count() == 0 and not pg.is_visible(".fsum") and pg.locator("table.tasks tbody tr:visible").count() == 1, "opening another route clears the filters")
    pg.evaluate("window.__drop({protocol:'3DXContent',data:{items:[{objectId:'CA1',displayName:'CA-OI000629352-00000001',objectType:'Change Action'}]}})")
    pg.wait_for_function("document.querySelector('.title') && document.querySelector('.title').textContent.indexOf('0000100') >= 0")
    check(True, "dropped Change Action finds its approval route")
    pg.evaluate("window.__drop('not json')")
    check("didn't contain" in pg.inner_text(".status"), "bad drop reported")
    # 8) not found / no results / physical id
    pg.fill(".rtv input", "zzz-nothing"); pg.click(".go"); pg.wait_for_function("document.querySelector('.status').textContent.indexOf('No routes') === 0")
    check(pg.locator(".title").count() == 0, "no results message, view cleared")
    pg.fill(".rtv input", "0" * 32); pg.click(".go"); pg.wait_for_function("document.querySelector('.status').classList.contains('error')")
    check("Object does not exist" in pg.inner_text(".status"), "unknown physical id shows the server error")
    pg.fill(".rtv input", R101); pg.keyboard.press("Enter"); pg.wait_for_selector(".title")
    check(True, "physical id + Enter opens the route")
    check(not errors, "no page errors %s" % errors)
    b.close()
print("\n%d failure(s)" % len(fails))
raise SystemExit(1 if fails else 0)
