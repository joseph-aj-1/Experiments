/*
 * Mfg Item Viewer - pdf-report: the main PDF pages (jsPDF): title, item details, the BOM table
 * with Specification and MEI columns, the appendix list page, footers and the DRAFT watermark.
 * Also the printable fallback page (when jsPDF cannot be downloaded) and saving bytes as a file.
 */
(function (M) {
  "use strict";

  function pdfFileName(v, st) {
    var base = (v.item.name || "item") + "_" + (v.item.title || "");
    return base.replace(/[^A-Za-z0-9._-]+/g, "_").replace(/_+/g, "_").replace(/_$/, "") + "_DRAFT_" + st.file + ".pdf";
  }
  // One row per BOM line (level 0 = the item itself) with display strings for every column.
  function pdfRows(v) {
    var lines = [{ level: 0, title: v.item.title, inst: "", name: v.item.name, type: M.typeLabel(v.item.type),
                   rev: v.item.revision, state: M.stateLabel(v.item.state), id: v.item.id }];
    v.rows.forEach(function (r) {
      lines.push({ level: r.level, title: (r.ref.title || "") + (r.cycle ? " (cycle - not expanded)" : r.truncated ? " (deeper levels not shown)" : ""),
                   inst: r.inst.name, name: r.ref.name, type: M.typeLabel(r.ref.type || (r.inst.referencedObject && r.inst.referencedObject.type)),
                   rev: r.ref.revision, state: M.stateLabel(r.ref.state), id: r.refId });
    });
    lines.forEach(function (l) {
      var sp = (v.specs || {})[l.id];
      l.specList = sp || [];
      l.spec = sp ? (sp.length ? "" : "-") : (v.specDone ? "-" : "(not loaded)");
      var e = v.mei[l.id];
      if (!e) { l.mei = v.meiError ? "-" : (v.meiDone ? "No MEI" : "(not loaded)"); l.mfr = l.mpn = l.q = ""; return; }
      if (!e.length) { l.mei = "No MEI"; l.mfr = l.mpn = l.q = ""; return; }
      l.mei = e.map(function (x) { return (x.m.title || "") + (x.m.name ? " (" + x.m.name + (x.m.revision ? ", " + x.m.revision : "") + ")" : ""); }).join("\n");
      l.mfr = e.map(function (x) { return x.m.manufacturer || ""; }).join("\n");
      l.mpn = e.map(function (x) { return x.m.mpn || ""; }).join("\n");
      l.q = e.map(function (x) { return (x.q.title || x.q.name || "") + (x.q.state ? " (" + x.q.state + (x.q.preferred === "TRUE" ? ", preferred" : "") + ")" : ""); }).join("\n");
    });
    return lines;
  }
  M.INK = [27, 39, 51]; M.MUTED = [91, 107, 122]; M.LINK = [0, 86, 134];
  // opts (optional): { parts: [appendix parts], total: total page count incl. appendix }
  M.buildPdf = function (JsPDF, v, opts) {
    opts = opts || {};
    var parts = opts.parts || [], partByKey = {};
    parts.forEach(function (p, i) { partByKey[p.spec.key] = p; p.no = i + 1; });
    var links = [];                                 // clickable areas -> appendix pages (added after merging)
    var st = opts.stamp || M.stamp();
    var doc = new JsPDF({ orientation: "landscape", unit: "pt", format: "letter" });
    var W = doc.internal.pageSize.getWidth(), H = doc.internal.pageSize.getHeight(), MG = 36;
    var y = MG;
    var ctxLabel = (M.app.ctx || "").replace(/^ctx::/, "");
    function curPage() { return doc.getCurrentPageInfo().pageNumber; }
    function pageHeader() {
      doc.setFont("helvetica", "normal"); doc.setFontSize(8); doc.setTextColor(110);
      doc.text(M.pdfText("Mfg Item Viewer - " + (v.item.title || v.item.name)), MG, MG - 14);
      doc.text(M.pdfText((M.app.tenant || "") + "  |  " + ctxLabel + "  |  generated " + st.text), W - MG, MG - 14, { align: "right" });
      doc.setDrawColor(210); doc.line(MG, MG - 9, W - MG, MG - 9);
      doc.setTextColor(M.INK[0], M.INK[1], M.INK[2]);
    }
    function newPage() { doc.addPage(); y = MG + 6; pageHeader(); }
    function need(h) { if (y + h > H - MG - 14) { newPage(); return true; } return false; }
    pageHeader(); y = MG + 6;

    // title
    doc.setFont("helvetica", "bold"); doc.setFontSize(16);
    doc.text(M.pdfText(v.item.title || v.item.name), MG, y + 12);
    doc.setFont("helvetica", "normal"); doc.setFontSize(9); doc.setTextColor(M.MUTED[0], M.MUTED[1], M.MUTED[2]);
    doc.text(M.pdfText(M.typeLabel(v.item.type) + "  -  " + (v.item.name || "")), MG, y + 26);
    doc.setTextColor(M.INK[0], M.INK[1], M.INK[2]); y += 46;

    // details (only if expanded on screen), two columns of label/value
    if (!M.detailsCollapsed()) {
      var half = Math.ceil(v.kv.length / 2), colW = (W - 2 * MG) / 2, lab = 92;
      doc.setFontSize(8.5);
      for (var i = 0; i < half; i++) {
        [v.kv[i], v.kv[i + half]].forEach(function (kv, c) {
          if (!kv) return;
          var x = MG + c * colW;
          doc.setTextColor(M.MUTED[0], M.MUTED[1], M.MUTED[2]); doc.text(M.pdfText(kv[0]), x, y);
          doc.setTextColor(M.INK[0], M.INK[1], M.INK[2]); doc.text(doc.splitTextToSize(M.pdfText(kv[1]), colW - lab - 10)[0] || "", x + lab, y);
        });
        y += 12;
      }
      y += 6;
    }

    // section heading + MEI / specification summaries
    need(70);
    doc.setFont("helvetica", "bold"); doc.setFontSize(10); doc.setTextColor(M.MUTED[0], M.MUTED[1], M.MUTED[2]);
    doc.text(M.pdfText("BOM AND MANUFACTURER EQUIVALENT ITEMS - " + v.rows.length + " BOM item" + (v.rows.length === 1 ? "" : "s") +
             (v.depth ? ", " + v.depth + " level" + (v.depth === 1 ? "" : "s") : "")), MG, y + 8);
    doc.setFont("helvetica", "normal"); doc.setFontSize(8);
    doc.text(M.pdfText(v.meiText || ""), MG, y + 20);
    doc.text(M.pdfText((v.specText || "") + (parts.length ? "  -  contents attached as an appendix (see the last pages)" : "")), MG, y + 30);
    doc.setTextColor(M.INK[0], M.INK[1], M.INK[2]); y += 38;

    // table
    var cols = [
      { k: "level", h: "Lvl", w: 22 }, { k: "title", h: "Item", w: 108 }, { k: "inst", h: "Instance", w: 68 },
      { k: "name", h: "Name", w: 80 }, { k: "type", h: "Type", w: 64 }, { k: "rev", h: "Rev", w: 22 }, { k: "state", h: "State", w: 38 },
      { k: "spec", h: "Specification", w: 82, spec: true },
      { k: "mei", h: "MEI", w: 88, mei: true }, { k: "mfr", h: "Manufacturer", w: 66, mei: true },
      { k: "mpn", h: "Mfr part no.", w: 54, mei: true }, { k: "q", h: "Qualification", w: 54, mei: true }
    ];
    var total = cols.reduce(function (a, c) { return a + c.w; }, 0), scale = (W - 2 * MG) / total;
    cols.forEach(function (c) { c.w *= scale; });
    var FS = 7.5, LH = 9, PAD = 3;
    function headerRow() {
      var h = LH + 2 * PAD, x = MG;
      cols.forEach(function (c) {
        if (c.mei) doc.setFillColor(233, 241, 247); else if (c.spec) doc.setFillColor(243, 238, 230); else doc.setFillColor(244, 246, 248);
        doc.rect(x, y, c.w, h, "F");
        doc.setFont("helvetica", "bold"); doc.setFontSize(FS); doc.setTextColor(M.INK[0], M.INK[1], M.INK[2]);
        doc.text(c.h, x + PAD, y + PAD + 7);
        x += c.w;
      });
      y += h; doc.setFont("helvetica", "normal");
    }
    headerRow();
    pdfRows(v).forEach(function (r) {
      doc.setFontSize(FS);
      var indent = r.level * 7;
      var specKeys = [];                    // spec-column line -> spec key (for links)
      var cells = cols.map(function (c) {
        var w = Math.max(c.w - 2 * PAD - (c.k === "title" ? indent : 0), 10);
        if (c.k === "spec" && r.specList.length) {
          var out = [];
          r.specList.forEach(function (s) {
            var label = s.fileId ? s.fileName : s.docTitle + " (no file)";
            var p = partByKey[s.key];
            if (p && p.pages) label += "  [A" + p.no + "]";
            doc.splitTextToSize(M.pdfText(label), w).forEach(function (ln) { out.push(ln); specKeys.push(s.key); });
          });
          return out;
        }
        var txt = c.k === "level" ? String(r.level) : M.pdfText(c.k === "title" && r.level ? "- " + r[c.k] : r[c.k]);
        return doc.splitTextToSize(txt, w);
      });
      var h = Math.max.apply(null, cells.map(function (l) { return l.length; })) * LH + 2 * PAD;
      if (need(h)) headerRow();
      var x = MG;
      cols.forEach(function (c, i) {
        if (r.level === 0) { doc.setFillColor(c.mei ? 238 : 244, c.mei ? 245 : 246, c.mei ? 250 : 248); doc.rect(x, y, c.w, h, "F"); }
        else if (c.mei) { doc.setFillColor(248, 251, 253); doc.rect(x, y, c.w, h, "F"); }
        doc.setFont("helvetica", (r.level === 0 || (c.k === "title" && r.level === 1)) ? "bold" : "normal");
        if (c.k === "spec" && specKeys.length) {
          doc.setFont("helvetica", "normal");
          cells[i].forEach(function (ln, j) {
            var p = partByKey[specKeys[j]], linked = p && p.pages;
            doc.setTextColor.apply(doc, linked ? M.LINK : M.INK);
            doc.text(ln, x + PAD, y + PAD + 7 + j * LH);
            if (linked) links.push({ page: curPage(), x: x + PAD, y: y + PAD + j * LH, w: Math.min(doc.getTextWidth(ln), c.w - 2 * PAD), h: LH, part: p });
          });
        } else {
          var muted = c.k === "level" || cells[i][0] === "No MEI" || cells[i][0] === "(not loaded)" || (c.k === "spec" && cells[i][0] === "-");
          doc.setTextColor(muted ? 110 : 27, muted ? 120 : 39, muted ? 130 : 51);
          doc.text(cells[i], x + PAD + (c.k === "title" ? indent : 0), y + PAD + 7);
        }
        x += c.w;
      });
      doc.setDrawColor(216, 222, 229); doc.line(MG, y + h, W - MG, y + h);
      y += h;
    });
    if (!v.rows.length) { need(16); doc.setFontSize(8.5); doc.setTextColor(110); doc.text("No BOM children.", MG, y + 12); }

    // appendix index: one line per specification file, with the page it starts on
    if (parts.length) {
      newPage();
      doc.setFont("helvetica", "bold"); doc.setFontSize(10); doc.setTextColor(M.MUTED[0], M.MUTED[1], M.MUTED[2]);
      doc.text("APPENDIX - SPECIFICATION DOCUMENTS", MG, y + 8);
      doc.setFont("helvetica", "normal"); doc.setFontSize(8);
      doc.text(M.pdfText("Files attached to the items above with a Specification Document link. Their contents follow, one section per file (A1, A2, ...)."), MG, y + 20);
      y += 30;
      var icols = [{ h: "#", w: 26 }, { h: "Attached to", w: 150 }, { h: "Document", w: 160 }, { h: "File", w: 170 }, { h: "Size", w: 50 }, { h: "In this PDF", w: 164 }];
      var it = icols.reduce(function (a, c) { return a + c.w; }, 0), sc = (W - 2 * MG) / it;
      icols.forEach(function (c) { c.w *= sc; });
      var ihead = function () {
        var x = MG; doc.setFont("helvetica", "bold"); doc.setFontSize(FS);
        icols.forEach(function (c) { doc.setFillColor(243, 238, 230); doc.rect(x, y, c.w, LH + 2 * PAD, "F"); doc.setTextColor(M.INK[0], M.INK[1], M.INK[2]); doc.text(c.h, x + PAD, y + PAD + 7); x += c.w; });
        y += LH + 2 * PAD; doc.setFont("helvetica", "normal");
      };
      ihead();
      parts.forEach(function (p) {
        var s = p.spec;
        var vals = ["A" + p.no, p.items.join("\n"), s.docTitle + "\n" + s.docName + (s.rev !== "" ? ", rev " + s.rev : "") + (s.state ? ", " + s.state : ""),
                    s.fileName || "(no file)", M.fmtSize(s.size), p.pages ? (opts.pageOf ? "Page " + opts.pageOf(p) : "Included") + " (" + p.pages + " page" + (p.pages === 1 ? "" : "s") + ")" + (p.note ? " - " + p.note : "")
                                                            : "Not included - " + (p.reason || "unknown reason")];
        doc.setFontSize(FS);
        var cl = icols.map(function (c, i) { return doc.splitTextToSize(M.pdfText(vals[i]), c.w - 2 * PAD); });
        var h = Math.max.apply(null, cl.map(function (l) { return l.length; })) * LH + 2 * PAD;
        if (need(h)) ihead();
        var x = MG;
        icols.forEach(function (c, i) {
          var linked = p.pages && (i === 0 || i === 3 || i === 5);
          doc.setTextColor.apply(doc, linked ? M.LINK : (i === 5 ? [179, 38, 30] : M.INK));
          doc.text(cl[i], x + PAD, y + PAD + 7);
          if (linked) links.push({ page: curPage(), x: x + PAD, y: y + PAD, w: Math.min(c.w - 2 * PAD, Math.max.apply(null, cl[i].map(function (l) { return doc.getTextWidth(l); }))), h: cl[i].length * LH, part: p });
          x += c.w;
        });
        doc.setDrawColor(216, 222, 229); doc.line(MG, y + h, W - MG, y + h);
        y += h;
      });
    }

    // footer + DRAFT watermark on every page (appendix pages get theirs when merged)
    var n = doc.getNumberOfPages(), N = opts.total || n;
    for (var pg = 1; pg <= n; pg++) {
      doc.setPage(pg);
      doc.setFont("helvetica", "normal"); doc.setFontSize(8); doc.setTextColor(110);
      doc.text("DRAFT - not released", MG, H - MG + 14);
      doc.text("Page " + pg + " of " + N, W - MG, H - MG + 14, { align: "right" });
      doc.saveGraphicsState();
      if (doc.GState) doc.setGState(new doc.GState({ opacity: 0.13 }));
      doc.setFont("helvetica", "bold"); doc.setFontSize(150); doc.setTextColor(179, 38, 30);
      var wm = "DRAFT", a = 30 * Math.PI / 180, tw = doc.getTextWidth(wm);
      doc.text(wm, W / 2 - (tw / 2) * Math.cos(a), H / 2 + (tw / 2) * Math.sin(a) + 40, { angle: 30 });
      doc.restoreGraphicsState();
    }
    return { doc: doc, file: pdfFileName(v, st), links: links, pages: n, H: H };
  };
  // Fallback when the PDF library can't be downloaded: printable page with the same watermark.
  M.printFallback = function (v) {
    var html = "<html><head><title>" + M.esc(pdfFileName(v, M.stamp())) + "</title><style>" +
      "@page{size:letter landscape;margin:12mm}body{font:11px Arial,sans-serif;color:#1b2733}" +
      ".wm{position:fixed;top:40%;left:0;right:0;text-align:center;font:bold 150px Arial;color:rgba(179,38,30,.13);transform:rotate(-30deg);z-index:9;pointer-events:none}" +
      "table{width:100%;border-collapse:collapse}th,td{border-bottom:1px solid #d8dee5;padding:3px 4px;text-align:left;vertical-align:top}" +
      "th{background:#f4f6f8}.foot{margin-top:8px;color:#6e7882}</style></head><body><div class='wm'>DRAFT</div>" +
      M.ui.details.innerHTML.replace(/<span class='tg'>.*?<\/span>/, "") + "<div class='foot'>DRAFT - not released</div></body></html>";
    var wdw = window.open("", "_blank");
    if (!wdw) throw new Error("Pop-ups are blocked, so the printable fallback could not open.");
    wdw.document.open(); wdw.document.write(html); wdw.document.close();
    setTimeout(function () { wdw.focus(); wdw.print(); }, 300);
  };

  M.saveBytes = function (bytes, name) {
    var url = URL.createObjectURL(new Blob([bytes], { type: "application/pdf" }));
    var a = M.el("a"); a.href = url; a.download = name; a.style.display = "none";
    document.body.appendChild(a); a.click();
    setTimeout(function () { a.remove(); URL.revokeObjectURL(url); }, 5000);
  };
})(window.MFV);
