import re, sys, os, pathlib
HERE = pathlib.Path(__file__).resolve().parent
os.chdir(HERE)
from playwright.sync_api import sync_playwright
APP = HERE.parent                       # the mfgitem-viewer folder (served as GitHub Pages in the tests)
PAGES = "https://joseph-aj-1.github.io/Experiments/mfgitem-viewer/"
html = open(APP / "index.html", encoding="utf-8").read()
mock = open("mock_platform.js").read()
# inject the mock before the widget's own script runs
page_html = html.replace("\n<body>", "\n<body><script>" + mock + "</script>", 1)
assert mock in page_html
open("harness.html", "w", encoding="utf-8").write(page_html)
fails = []
def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg); 
    if not cond: fails.append(msg)
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 760, "height": 900}, accept_downloads=True)
    lib_hits = []; pages_hits = []
    def pages(block=()):
        # serve the mfgitem-viewer folder as if it were GitHub Pages; `block` = path prefixes to fail
        def h(route):
            path = route.request.url.split(PAGES, 1)[-1].split("?", 1)[0]
            pages_hits.append(path)
            if any(path.startswith(b_) for b_ in block): return route.abort()
            f_ = APP / path
            if not f_.is_file(): return route.fulfill(status=404, body="not found", headers={"Access-Control-Allow-Origin": "*"})
            if path.startswith("vendor/"): lib_hits.append(path[7:])
            ct = {"js": "application/javascript", "css": "text/css", "json": "application/json", "html": "text/html"}.get(f_.suffix[1:], "application/octet-stream")
            route.fulfill(status=200, body=f_.read_bytes(), headers={"Access-Control-Allow-Origin": "*", "Content-Type": ct})
        return h
    ctx.route(PAGES + "**", pages())
    ctx.route("https://cdnjs.cloudflare.com/**", lambda route: route.abort())
    ctx.route("https://cdn.jsdelivr.net/**", lambda route: route.abort())
    FIX = {"E313E8104D0D3D006AC3CAAE4008448C": "00753-2350.pdf", "F100": "AWS-100.docx", "F101X": "Tolerances.xlsx", "F101D": "OldSpec.doc"}
    fcs_hits = []
    def fcs(route):
        fid = route.request.url.split("jobTicket=T-")[-1]; fcs_hits.append(fid)
        if fid not in FIX: return route.abort()
        route.fulfill(status=200, body=(HERE / "fixtures" / FIX[fid]).read_bytes(), headers={"Access-Control-Allow-Origin": "*", "Content-Type": "application/octet-stream"})
    ctx.route("https://eu1-demo-dfcs.3dexperience.3ds.com/**", fcs)
    pg = ctx.new_page()
    errors = []; pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto((HERE / "harness.html").as_uri())
    pg.wait_for_function("document.querySelector('.status') && document.querySelector('.status').textContent.startsWith('Ready')", timeout=5000)
    import json as _json
    man = _json.loads((APP / "manifest.json").read_text())
    loaded = [h_ for h_ in pages_hits if h_.startswith("js/") or h_.startswith("css/")]
    check(pages_hits[0] == "manifest.json" and [h_ for h_ in loaded if h_.startswith("js/")] == man["js"] and "css/mfgitem-viewer.css" in loaded,
          "index.html loads manifest.json, then the CSS and every script in manifest order from GitHub Pages")
    check(pg.evaluate("getComputedStyle(document.querySelector('.go')).backgroundColor") == "rgb(0, 86, 134)", "stylesheet applied")
    check(pg.inner_text(".ctx") == "Context: VPLMProjectLeader.Company Name.Common Space", "security context picked from preferred credentials")
    check(pg.evaluate("window.__pref && window.__pref.options.length") == 2, "context preference list offered (2 options)")
    # 1) search with a single hit -> straight to details
    pg.fill(".mfv input", "AJ MA 101"); pg.click(".go")
    pg.wait_for_selector(".title"); pg.wait_for_function("document.querySelector('.status').textContent === ''")
    check("AJ MA 101" in pg.inner_text(".title"), "details title shown")
    txt = pg.inner_text(".details")
    check("mass-OI000629352-00000004" in txt and "In Work" in txt and "Planning required\nYes" in txt, "details fields rendered with labels")
    check("BOM AND MANUFACTURER EQUIVALENT ITEMS \u2014 2 BOM ITEMS, 2 LEVELS" in txt.upper() and "AJ MA 100.0" in txt and "mass-OI000629352-00000003" in txt, "renamed heading counts BOM items/levels; child row shows instance + name")
    rows = pg.evaluate("Array.from(document.querySelectorAll('.details table.bom tbody tr')).map(function(r){return [r.cells[0].textContent, r.cells[1].textContent, parseInt(r.cells[1].style.paddingLeft)]})")
    check(len(rows) == 3 and rows[0][0] == "0" and rows[0][1] == "AJ MA 101" and rows[1][0] == "1" and rows[1][1].endswith("AJ MA 100") and rows[2][0] == "2" and "Continuous Provided Material00000001" in rows[2][1], "level 0 (opened item), then levels 1 and 2 depth-first")
    check(rows[2][2] > rows[1][2], "level-2 row is indented further than level 1")
    # MEI columns inside the BOM table
    pg.wait_for_function("document.querySelector('.meisum') && document.querySelector('.meisum').textContent.indexOf('of 3 items') >= 0", timeout=5000)
    check(pg.locator(".mei").count() == 0 and pg.locator("table.meit").count() == 0, "no separate MEI section any more")
    heads = pg.evaluate("Array.from(document.querySelectorAll('.details table.bom thead th')).map(function(h){return h.textContent})")
    check(heads[-4:] == ["MEI", "Manufacturer", "Mfr part no.", "Qualification"], "BOM table has MEI, Manufacturer, Mfr part no., Qualification columns")
    cells = pg.evaluate("Array.from(document.querySelectorAll('.details table.bom tbody tr')).map(function(r){return Array.from(r.querySelectorAll('.mei-cell')).map(function(c){return c.textContent})})")
    check(cells[0][0] == "No MEI" and cells[1][0] == "No MEI", "items without a qualification show No MEI in the BOM row")
    pp = cells[2]
    check(pp[0].startswith("AJ MEI PP 100") and "prd-OI000629352-00000002" in pp[0] and pp[1] == "Hi-Tech Supplier" and pp[2] == "AJ MEI PP 100" and pp[3].startswith("MQ-100000"),
          "AJ PP 100's BOM row shows its MEI, manufacturer, part no. and qualification")
    check("1 of 3 items have a Manufacturer Equivalent Item" in pg.inner_text(".meisum"), "MEI summary under the heading")
    sc = pg.evaluate("window.__sourcingCalls")
    posts = [c for c in sc if c["method"] == "POST"]
    check(len(posts) == 1 and posts[0]["csrf"] == "SRC-TOKEN" and posts[0]["tenant"] == "OI000629352", "one batched contextLocate POST with Sourcing CSRF token and tenant")
    # Specification column (SpecificationDocument links, files as hyperlinks)
    pg.wait_for_function("document.querySelector('.specsum') && document.querySelector('.specsum').textContent.indexOf('Specifications:') === 0", timeout=5000)
    check(heads[7] == "Specification", "BOM table has a Specification column after State")
    spc = pg.evaluate("Array.from(document.querySelectorAll('.details table.bom tbody tr')).map(function(r){return Array.from(r.querySelectorAll('.sc a.spec')).map(function(a){return a.textContent})})")
    check(spc[0] == ["XLSXTolerances.xlsx", "DOCOldSpec.doc", "PDFBlocked.pdf"] and spc[1] == ["DOCXAWS-100.docx"] and spc[2] == ["PDF00753-2350.pdf"],
          "each row lists its Specification files as links with a type badge (%s)" % spc)
    check("Specifications: 5 files on 3 of 3 items" in pg.inner_text(".specsum"), "specification summary under the heading")
    tip = pg.get_attribute(".details tr[data-mid='E313E810E8DD0E006ABF8AF700009C79'] a.spec", "title")
    check("00753-2350" in tip and "DOC-OI000629352-0000001" in tip and "1.5 MB" in tip, "link tooltip shows document title, name, revision, state and size")
    dcalls = [c["path"] for c in pg.evaluate("window.__calls") if "/documents/parentId/" in c["path"]]
    check(len(dcalls) == 3 and all("parentRelName=SpecificationDocument" in c and "include=files" in c for c in dcalls), "one getRelatedDocuments call per item, relation SpecificationDocument")
    with ctx.expect_page(timeout=10000) as pop:
        pg.click(".details tr[data-mid='E313E810E8DD0E006ABF8AF700009C79'] a.spec")
    pw_ = pop.value
    for _ in range(50):
        if "E313E8104D0D3D006AC3CAAE4008448C" in fcs_hits: break
        pg.wait_for_timeout(100)
    check("E313E8104D0D3D006AC3CAAE4008448C" in fcs_hits, "the new tab requests the file from the file server (FCS)")
    tc = pg.evaluate("window.__ticketCalls")
    check(tc and tc[-1]["method"] == "PUT" and tc[-1]["csrf"] == "SPACE-TOKEN" and tc[-1]["file"] == "E313E8104D0D3D006AC3CAAE4008448C",
          "clicking a spec gets a download ticket (PUT + 3DSpace CSRF) and opens the file in a new tab")
    check("AJ MA 101" in pg.inner_text(".title"), "clicking a spec link does not drill into the row")
    try: pw_.close()
    except Exception: pass
    fcs_hits.clear()
    pg.screenshot(path="shot_ma101.png", full_page=True)
    # PDF export (details expanded)
    check(pg.get_attribute(".pdf", "aria-disabled") == "false", "Export PDF enabled once an item is shown")
    with pg.expect_download(timeout=15000) as dl:
        pg.click(".pdf")
    d = dl.value; pdf_path = HERE / "out_ma101.pdf"; d.save_as(pdf_path)
    check(re.match(r"mass-OI000629352-00000004_AJ_MA_101_DRAFT_\d{8}-\d{4}\.pdf$", d.suggested_filename) is not None, "PDF file name: <name>_<title>_DRAFT_<date-time>.pdf")
    from pypdf import PdfReader
    rd = PdfReader(str(pdf_path)); txt_pdf = "\n".join(pg_.extract_text() for pg_ in rd.pages)
    box = rd.pages[0].mediabox
    check(round(float(box.width)) == 792 and round(float(box.height)) == 612, "landscape US Letter pages")
    check(txt_pdf.count("DRAFT") >= 2 * len(rd.pages) and "DRAFT - not released" in txt_pdf, "DRAFT watermark + footer on every page")
    np_ = len(rd.pages); ptxt = [x.extract_text() for x in rd.pages]
    check(all(("Page %d of %d" % (i_ + 1, np_)) in t_ for i_, t_ in enumerate(ptxt)), "page x of %d on every page, appendix included" % np_)
    check(all(s_ in txt_pdf for s_ in ["SPEC 00753-2350 PAGE 1", "SPEC 00753-2350 PAGE 2", "PAGE 3 LANDSCAPE"]), "PDF spec pages appended (incl. landscape page)")
    check(all(s_ in txt_pdf for s_ in ["Assembly Work Specification AWS-100", "Torque the fasteners to 12 Nm", "Clean the mating surfaces", "25 Nm", "End of specification text"]),
          "Word spec converted: heading, text, numbered list, table")
    check(all(s_ in txt_pdf for s_ in ["Sheet: Tolerances", "Hole 1", "Hole 80", "Sheet: Notes", "Inspect every 10th part"]), "Excel spec converted: every sheet and row")
    check("APPENDIX - SPECIFICATION DOCUMENTS" in txt_pdf and "Not included - old .doc format" in txt_pdf and "Not included - download blocked" in txt_pdf,
          "appendix list explains files that could not be included")
    check(sum(1 for t_ in ptxt if "Specification: 00753-2350.pdf" in t_) == 4 and sum(1 for t_ in ptxt if "attached to AJ PP 100" in t_ or "attached to Continuous" in t_) == 4,
          "each appended page has a header naming the spec and the item it's attached to")
    pidx = {pp_.indirect_reference.idnum: i_ for i_, pp_ in enumerate(rd.pages)}
    dests = []
    for i_ in range(np_):
        for an in (rd.pages[i_].get("/Annots") or []):
            an = an.get_object()
            if an.get("/Subtype") == "/Link" and "/Dest" in an: dests.append((i_, pidx.get(an["/Dest"][0].idnum)))
    first_pdf = next(i_ for i_, t_ in enumerate(ptxt) if "SPEC 00753-2350 PAGE 1" in t_)
    check(any(d_[0] == 0 and d_[1] == first_pdf for d_ in dests) and len(dests) >= 6, "spec names in the table and index link to their appendix pages (%d links)" % len(dests))
    rot_ = [i_ for i_, pp_ in enumerate(rd.pages) if (pp_.get("/Rotate") or 0)]
    check(not rot_, "rotated source pages are drawn upright")
    check(sorted(set(lib_hits)) == ["jspdf.umd.min.js", "mammoth.browser.min.js", "pdf-lib.min.js", "xlsx.full.min.js"], "jsPDF, pdf-lib, mammoth and SheetJS loaded on demand from the GitHub Pages copies (vendor/)")
    check(pg.evaluate("window.__anonDefine || 0") == 0, "no library was captured by the dashboard AMD loader")
    check("3 of 5 specifications included" in pg.inner_text(".status"), "status says how many specs made it into the PDF")
    os.system("pdftoppm -r 40 -png %s pdfpage >/dev/null 2>&1" % pdf_path)
    check(all(s_ in txt_pdf for s_ in ["AJ MA 101", "AJ MA 100", "Material00000001", "AJ MEI PP 100", "Hi-Tech Supplier", "MQ-100000",
                                       "BOM AND MANUFACTURER EQUIVALENT ITEMS", "Planning required", "1 of 3 items have a Manufacturer Equivalent Item"]),
          "PDF contains details, BOM rows and MEI info as shown")
    check(pg.evaluate("window.__anonDefine || 0") == 0 and pg.evaluate("typeof window.define") == "function" and pg.evaluate("typeof window.require") == "function",
          "jsPDF loaded without tripping the dashboard's AMD loader; define/require restored")
    check("PDF saved" in pg.inner_text(".status"), "status confirms the saved PDF")
    # download blocked by CORS -> platform proxy fallback
    import base64 as b64m
    pg.evaluate("window.__proxyBytes = {F101B: '%s'}" % b64m.b64encode((HERE / "fixtures" / "00753-2350.pdf").read_bytes()).decode())
    with pg.expect_download(timeout=20000) as dl3:
        pg.click(".pdf")
    p3 = HERE / "out_proxy.pdf"; dl3.value.save_as(p3)
    t3 = "\n".join(x.extract_text() for x in PdfReader(str(p3)).pages)
    check(pg.evaluate("window.__proxyCalls") >= 1 and "Specification: Blocked.pdf" in t3 and "4 of 5 specifications included" in pg.inner_text(".status"),
          "when the file server blocks the browser, the download goes through the platform proxy")
    # multi-page: synthetic 120-row BOM -> header row repeated, watermark + page numbers on every page
    uri = pg.evaluate("""(function(){
      var v = JSON.parse(JSON.stringify(window.__lastView || {}));
      var base = { item: {id:'X',title:'Big BOM',name:'mass-BIG',type:'CreateAssembly',revision:'A',state:'IN_WORK'},
                   kv: [['Name','mass-BIG']], depth: 3, mei: {}, meiText: '0 of 121 items', meiDone: true, rows: [] };
      for (var i=0;i<120;i++) base.rows.push({level:1+(i%3), ref:{title:'Part '+i, name:'p-'+i, type:'Provide', revision:'A', state:'IN_WORK'}, inst:{name:'Part '+i+'.1'}, refId:'R'+i});
      return window.__mfvPdfTest(window.jspdf.jsPDF, base); })()""")
    import base64
    big = HERE / "out_big.pdf"; big.write_bytes(base64.b64decode(uri.split(",",1)[1]))
    rb = PdfReader(str(big)); n_ = len(rb.pages)
    pages_txt = [x.extract_text() for x in rb.pages]
    check(n_ >= 3 and all(("Lvl" in pt and "Qualification" in pt and "DRAFT" in pt and ("Page %d of %d" % (i_+1, n_)) in pt) for i_, pt in enumerate(pages_txt))
          and "Part 119" in pages_txt[-1], "long BOM pages correctly: header row, watermark and page x of y on every page (%d pages)" % n_)
    # collapsible details
    check(pg.locator(".dbody").is_visible() and "Hide details" in pg.inner_text(".dtoggle"), "details expanded by default with a Hide details control")
    pg.click(".dtoggle .tg")
    check(not pg.locator(".dbody").is_visible() and "Show details" in pg.inner_text(".dtoggle")
          and pg.locator(".details table.bom").is_visible(), "clicking the title collapses details; BOM/MEI table stays")
    check(pg.evaluate("widget.getValue('detailsCollapsed')") == "true", "collapsed choice saved as a widget value")
    with pg.expect_download(timeout=15000) as dl2:
        pg.click(".pdf")
    p2 = HERE / "out_collapsed.pdf"; dl2.value.save_as(p2)
    t2 = "\n".join(x.extract_text() for x in PdfReader(str(p2)).pages)
    check("Planning required" not in t2 and "AJ MEI PP 100" in t2, "collapsed view exports without the details list")
    # 2) click the BOM child -> navigates to AJ MA 100 and its own child
    pg.click(".details tr.pick"); pg.wait_for_function("document.querySelector('.title') && document.querySelector('.title').textContent.indexOf('AJ MA 100') === 0")
    check("Continuous Provided Material00000001" in pg.inner_text(".details"), "clicking a BOM child opens it (drill-down)")
    check(not pg.locator(".dbody").is_visible(), "collapsed state carries over to the next item opened")
    pg.focus(".dtoggle"); pg.keyboard.press("Enter")
    check(pg.locator(".dbody").is_visible() and pg.get_attribute(".dtoggle", "aria-expanded") == "true", "keyboard (Enter) expands the details again")
    # 3) multi-hit search -> pick list
    pg.fill(".mfv input", "AJ MA"); pg.click(".go"); pg.wait_for_selector(".results tr.pick")
    check(pg.locator(".results tr.pick").count() == 2 and "2 matches" in pg.inner_text(".status"), "multiple matches shown as a pick list")
    pg.locator(".results tr.pick").nth(0).click(); pg.wait_for_selector(".title")
    check(pg.locator(".results tr").count() == 0, "picking a match opens it and clears the list")
    # 4) drag & drop payload
    pg.evaluate("window.__drop({protocol:'3DXContent',data:{items:[{objectId:'E313E810E8DD0E006ABF8AF700009C79',displayName:'Continuous Provided Material00000001',objectType:'ProcessContinuousProvide'}]}})")
    pg.wait_for_function("document.querySelector('.title') && document.querySelector('.title').textContent.indexOf('Continuous') === 0")
    check("No BOM children" in pg.inner_text(".details"), "drop opens item; empty BOM message")
    # cycle: make CPR contain AJ MA 101 again -> must stop, not loop forever
    pg.evaluate("window.__makeCycle()")
    pg.fill(".mfv input", "AJ MA 101"); pg.click(".go")
    pg.wait_for_function("document.querySelector('.details') && document.querySelector('.details').textContent.indexOf('cycle') >= 0", timeout=5000)
    check(pg.locator(".details table.bom tbody tr").count() == 4, "cyclic BOM stops at the repeat and is flagged")
    pg.evaluate("window.__breakCycle()")
    # 5) physical ID typed directly, 6) no results, 7) not found error
    pg.fill(".mfv input", "E313E810E8DD0E006ABE8924000020C1"); pg.click(".go")
    pg.wait_for_function("document.querySelector('.title') && document.querySelector('.title').textContent.indexOf('AJ MA 100') === 0")
    check(not any("search" in c["path"] and "E313" in c["path"] for c in pg.evaluate("window.__calls")), "physical ID skips search")
    pg.fill(".mfv input", "nothing-like-this"); pg.click(".go"); pg.wait_for_function("document.querySelector('.status').textContent.startsWith('No Manufacturing')")
    check(True, "no-results message")
    pg.fill(".mfv input", "00000000000000000000000000000000"); pg.click(".go"); pg.wait_for_selector(".status.error")
    check("Object not found" in pg.inner_text(".status"), "API error surfaced to the user")
    calls = pg.evaluate("window.__calls")
    check(all("tenant=OI000629352" in c["path"] for c in calls), "every call carries tenant=OI000629352")
    check(all(c["ctx"] == "ctx::VPLMProjectLeader.Company Name.Common Space" for c in calls if "dsmfg" in c["path"]), "every dsmfg call carries SecurityContext")
    check(pg.evaluate("window.__title") is not None, "widget title updated")
    check(not errors, "no JavaScript errors" + (": " + "; ".join(errors) if errors else ""))
    # 8) XSS safety: title with markup is escaped
    # 8) markup in item data is shown as text, never executed
    pg.fill(".mfv input", "<img src=x onerror=window.__xss=1>"); pg.click(".go"); pg.wait_for_timeout(300)
    check(pg.evaluate("window.__xss") is None, "search text with HTML is not executed")

    # 9) loader drops the trailing start-up script -> backup start must still work
    html2 = page_html.replace(page_html[page_html.rindex("</body>") + len("</body>"):page_html.rindex("</html>")], "")
    open("harness_nostart.html", "w", encoding="utf-8").write(html2)
    pg2 = ctx.new_page(); pg2.goto((HERE / "harness_nostart.html").as_uri())
    pg2.wait_for_function("document.querySelector('.status') && document.querySelector('.status').textContent.startsWith('Ready')", timeout=8000)
    check(pg2.locator(".go").is_visible(), "backup start-up works without the trailing script; Search button visible")
    # 10) platform modules fail to load -> visible error, not a frozen status
    html3 = page_html.replace("<body><script>", "<body><script>window.__failRequire=true;", 1)
    open("harness_fail.html", "w", encoding="utf-8").write(html3)
    pg3 = ctx.new_page(); pg3.goto((HERE / "harness_fail.html").as_uri())
    pg3.wait_for_selector(".status.error", timeout=5000)
    check("Could not load platform modules" in pg3.inner_text(".status"), "module-load failure is reported in the widget")
    # 11) Sourcing not in the service registry -> derived URL still works
    html4 = page_html.replace("<body><script>", "<body><script>window.__noSourcingRegistry=true;", 1)
    open("harness_nosrc.html", "w", encoding="utf-8").write(html4)
    pg4 = ctx.new_page(); pg4.goto((HERE / "harness_nosrc.html").as_uri())
    pg4.wait_for_function("document.querySelector('.status') && document.querySelector('.status').textContent.startsWith('Ready')", timeout=8000)
    pg4.fill(".mfv input", "AJ MA 101"); pg4.click(".go"); pg4.wait_for_function("document.querySelector('.meisum') && document.querySelector('.meisum').textContent.indexOf('of 3 items') >= 0", timeout=5000)
    check("Hi-Tech Supplier" in pg4.inner_text(".details table.bom"), "Sourcing URL derived from 3DSpace when the registry has no entry")
    # 12) Sourcing failure is shown in the MEI section only; BOM still visible
    html5 = page_html.replace("<body><script>", "<body><script>window.__failQual=true;", 1)
    open("harness_qfail.html", "w", encoding="utf-8").write(html5)
    pg5 = ctx.new_page(); pg5.goto((HERE / "harness_qfail.html").as_uri())
    pg5.wait_for_function("document.querySelector('.status') && document.querySelector('.status').textContent.startsWith('Ready')", timeout=8000)
    pg5.fill(".mfv input", "AJ MA 101"); pg5.click(".go"); pg5.wait_for_selector(".meisum.error", timeout=5000)
    check("Sourcing is down" in pg5.inner_text(".meisum") and pg5.locator(".details table.bom tbody tr").count() == 3, "MEI lookup failure shown under the heading; BOM rows still shown")
    # 13) scrolling: the widget area scrolls both ways when content is larger than the widget
    pg6 = ctx.new_page(); pg6.set_viewport_size({"width": 600, "height": 380})
    pg6.goto((HERE / "harness.html").as_uri())
    pg6.wait_for_function("document.querySelector('.status') && document.querySelector('.status').textContent.startsWith('Ready')", timeout=8000)
    pg6.fill(".mfv input", "AJ MA 101"); pg6.click(".go")
    pg6.wait_for_function("document.querySelector('.meisum') && document.querySelector('.meisum').textContent.indexOf('of 3') >= 0", timeout=5000)
    sc = pg6.evaluate("(function(){var e=document.querySelector('.mfv'),cs=getComputedStyle(e);return {ov:cs.overflowX+'/'+cs.overflowY,sh:e.scrollHeight,ch:e.clientHeight,sw:e.scrollWidth,cw:e.clientWidth}})()")
    check(sc["ov"] == "auto/auto" and sc["sh"] > sc["ch"] and sc["sw"] > sc["cw"], "widget area scrolls vertically and horizontally (%s)" % sc)
    pg6.evaluate("document.querySelector('.mfv').scrollTo(400, 600)")
    pos = pg6.evaluate("[document.querySelector('.mfv').scrollLeft, document.querySelector('.mfv').scrollTop]")
    check(pos[0] > 0 and pos[1] > 0, "scroll position moves both ways")
    check(pg6.evaluate("document.documentElement.scrollHeight <= window.innerHeight + 1"), "no second (page-level) scrollbar")
    # 14) cdnjs blocked -> printable fallback with watermark opens
    ctx2 = b.new_context(viewport={"width": 1000, "height": 800})
    ctx2.route(PAGES + "**", pages(block=("vendor/",)))
    ctx2.route("https://cdnjs.cloudflare.com/**", lambda route: route.abort())
    ctx2.route("https://cdn.jsdelivr.net/**", lambda route: route.abort())
    pg7 = ctx2.new_page(); pg7.goto((HERE / "harness.html").as_uri())
    pg7.wait_for_function("document.querySelector('.status') && document.querySelector('.status').textContent.startsWith('Ready')", timeout=8000)
    pg7.fill(".mfv input", "AJ MA 101"); pg7.click(".go"); pg7.wait_for_selector(".details table.bom")
    with ctx2.expect_page(timeout=10000) as popup:
        pg7.click(".pdf")
    pw = popup.value; pw.wait_for_load_state()
    check("DRAFT" in pw.inner_text(".wm") and pw.locator("table.bom").count() == 1 and "printable version" in pg7.inner_text(".status"),
          "if the PDF library can't be downloaded anywhere, a printable watermarked version opens instead")
    # 15) GitHub Pages not reachable -> clear message in the widget
    ctx3 = b.new_context(viewport={"width": 900, "height": 600})
    ctx3.route(PAGES + "**", lambda route: route.fulfill(status=404, body="nf", headers={"Access-Control-Allow-Origin": "*"}))
    pg8 = ctx3.new_page(); pg8.goto((HERE / "harness.html").as_uri())
    pg8.wait_for_function("document.body.textContent.indexOf('Could not start') >= 0", timeout=8000)
    check("GitHub Pages is enabled" in pg8.inner_text("body") and "HTTP 404" in pg8.inner_text("body"), "if GitHub Pages is not reachable the widget says so")
    b.close()
print("\n%d failure(s)" % len(fails)); sys.exit(1 if fails else 0)
