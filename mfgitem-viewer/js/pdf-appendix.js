/*
 * Mfg Item Viewer - pdf-appendix: the Specification appendix of the PDF.
 * Downloads each spec file (FCS ticket; platform proxy as fallback), turns Word and Excel
 * files into PDF pages, then merges everything with pdf-lib: spec pages are scaled into a
 * frame with a header, footer ("Page x of N") and DRAFT watermark, and table/index entries
 * link to their pages.
 */
(function (M) {
  "use strict";

  var EMBED_MAX = 30 * 1048576;            // bigger files are listed, not embedded
  // distinct spec files in table order, with the items they are attached to
  M.specPartsFor = function (v) {
    var lines = [{ id: v.item.id, t: v.item.title || v.item.name }].concat(v.rows.map(function (r) { return { id: r.refId, t: r.ref.title || r.ref.name || r.refId }; }));
    var byKey = {}, parts = [];
    lines.forEach(function (l) {
      ((v.specs || {})[l.id] || []).forEach(function (s) {
        if (!byKey[s.key]) { byKey[s.key] = { spec: s, items: [] }; parts.push(byKey[s.key]); }
        if (byKey[s.key].items.indexOf(l.t) < 0) byKey[s.key].items.push(l.t);
      });
    });
    return parts;
  };
  // FCS download: direct (CORS) first, then through the platform proxy
  function fetchBytes(url) {
    return fetch(url, { credentials: "omit" }).then(function (r) {
      if (!r.ok) throw new Error("file server answered HTTP " + r.status);
      return r.arrayBuffer();
    }).catch(function (e1) {
      if (!M.WAFData.proxifiedRequest) throw new Error("download blocked (" + e1.message + ")");
      return new Promise(function (resolve, reject) {
        M.WAFData.proxifiedRequest(url, {
          method: "GET", type: "arraybuffer", responseType: "arraybuffer",
          onComplete: function (d) {
            if (d instanceof ArrayBuffer) resolve(d);
            else if (d && d.buffer instanceof ArrayBuffer) resolve(d.buffer);
            else if (typeof Blob !== "undefined" && d instanceof Blob) d.arrayBuffer().then(resolve, reject);
            else reject(new Error("download blocked (" + e1.message + "); the proxy returned no file data"));
          },
          onFailure: function () { reject(new Error("download blocked (" + e1.message + ")")); },
          onTimeout: function () { reject(new Error("download timed out")); }
        });
      });
    });
  }
  function loadImages(imgs) {        // natural sizes for embedded Word images
    return Promise.all(imgs.map(function (im) {
      return new Promise(function (res) {
        var src = im.getAttribute("src") || "";
        if (!/^data:image\/(png|jpe?g);base64,/i.test(src)) return res();
        var I = new Image(); I.onload = function () { im.__w = I.naturalWidth; im.__h = I.naturalHeight; res(); }; I.onerror = function () { res(); }; I.src = src;
      });
    }));
  }
  // Word (.docx -> HTML via mammoth) to PDF pages: headings, paragraphs, lists, tables, PNG/JPEG images
  function renderHtmlPdf(JsPDF, html) {
    var body = new DOMParser().parseFromString("<div>" + html + "</div>", "text/html").body;
    var imgs = Array.prototype.slice.call(body.querySelectorAll("img"));
    return loadImages(imgs).then(function () {
      var doc = new JsPDF({ unit: "pt", format: "letter" });
      var W = doc.internal.pageSize.getWidth(), H = doc.internal.pageSize.getHeight(), MG = 54, TOP = 54, BOT = 54, y = TOP, skipped = 0;
      function need(h) { if (y + h > H - BOT) { doc.addPage(); y = TOP; } }
      function para(text, size, bold, indent, after) {
        text = M.pdfText(String(text || "").replace(/\s+/g, " ").trim());
        if (!text) return;
        doc.setFont("helvetica", bold ? "bold" : "normal"); doc.setFontSize(size); doc.setTextColor(M.INK[0], M.INK[1], M.INK[2]);
        var lh = size * 1.3;
        doc.splitTextToSize(text, W - 2 * MG - (indent || 0)).forEach(function (ln) { need(lh); doc.text(ln, MG + (indent || 0), y + size); y += lh; });
        y += after || 0;
      }
      function image(im) {
        if (!im.__w) { skipped++; return; }
        var maxW = W - 2 * MG, maxH = H - TOP - BOT, s = Math.min(1, maxW / im.__w, maxH / im.__h);
        var w = im.__w * s * 0.75, h = im.__h * s * 0.75;           // px -> pt
        if (w > maxW) { h *= maxW / w; w = maxW; }
        need(h + 6);
        try { doc.addImage(im.getAttribute("src"), /png/i.test(im.getAttribute("src").slice(0, 20)) ? "PNG" : "JPEG", MG, y, w, h); y += h + 6; } catch (imgErr) { skipped++; }
      }
      function table(tbl) {
        var rows = Array.prototype.map.call(tbl.rows, function (tr) { return Array.prototype.map.call(tr.cells, function (td) { return M.pdfText(td.textContent.replace(/\s+/g, " ").trim()); }); });
        if (!rows.length) return;
        var nc = Math.max.apply(null, rows.map(function (r) { return r.length; })), cw = (W - 2 * MG) / nc, FS = 8.5, LH = 10.5, PAD = 3;
        y += 2;
        rows.forEach(function (r, ri) {
          doc.setFont("helvetica", ri === 0 ? "bold" : "normal"); doc.setFontSize(FS);
          var cl = []; for (var c = 0; c < nc; c++) cl.push(doc.splitTextToSize(r[c] || "", cw - 2 * PAD));
          var h = Math.max.apply(null, cl.map(function (l) { return l.length; })) * LH + 2 * PAD;
          need(h);
          for (c = 0; c < nc; c++) {
            if (ri === 0) { doc.setFillColor(244, 246, 248); doc.rect(MG + c * cw, y, cw, h, "F"); }
            doc.setDrawColor(190, 198, 206); doc.rect(MG + c * cw, y, cw, h, "S");
            doc.setTextColor(M.INK[0], M.INK[1], M.INK[2]); doc.text(cl[c], MG + c * cw + PAD, y + PAD + FS);
          }
          y += h;
        });
        y += 8;
      }
      function ownText(n) { var c = n.cloneNode(true); Array.prototype.forEach.call(c.querySelectorAll("ul,ol"), function (x) { x.remove(); }); return c.textContent; }
      function walk(node, depth) {
        Array.prototype.forEach.call(node.childNodes, function (n) {
          if (n.nodeType === 3) { para(n.textContent, 10, false, 0, 4); return; }
          if (n.nodeType !== 1) return;
          var t = n.tagName.toLowerCase(), m = /^h([1-6])$/.exec(t);
          if (m) { y += 4; para(n.textContent, [17, 14.5, 12.5, 11.5, 10.5, 10][m[1] - 1], true, 0, 4); }
          else if (t === "p") {
            var strong = n.querySelector("strong"), allBold = strong && strong.textContent.trim() === n.textContent.trim() && n.textContent.trim();
            para(n.textContent, 10, !!allBold, 0, 6);
            Array.prototype.forEach.call(n.querySelectorAll("img"), image);
          }
          else if (t === "ul" || t === "ol") {
            var k = 0;
            Array.prototype.forEach.call(n.children, function (li) {
              if (li.tagName.toLowerCase() !== "li") return;
              para((t === "ol" ? (++k) + ". " : "- ") + ownText(li), 10, false, 14 * (depth + 1), 2);
              Array.prototype.forEach.call(li.children, function (sub) { if (/^(ul|ol)$/i.test(sub.tagName)) walk({ childNodes: [sub] }, depth + 1); });
            });
            y += 4;
          }
          else if (t === "table") table(n);
          else if (t === "img") image(n);
          else if (t === "br") y += 6;
          else walk(n, depth);
        });
      }
      walk(body.firstChild || body, 0);
      if (doc.getNumberOfPages() === 1 && y === TOP) para("(The document has no readable text.)", 10, false, 0, 0);
      return { bytes: doc.output("arraybuffer"), note: skipped ? skipped + " image" + (skipped === 1 ? "" : "s") + " not shown" : "" };
    });
  }
  // Excel / CSV to PDF pages: one table per sheet, first row repeated on each page
  function renderSheetsPdf(JsPDF, XLSX, wb) {
    var doc = new JsPDF({ orientation: "landscape", unit: "pt", format: "letter" });
    var W = doc.internal.pageSize.getWidth(), H = doc.internal.pageSize.getHeight(), MG = 36, TOP = 50, BOT = 44, y = TOP;
    var MAXR = 2000, MAXC = 40, notes = [];
    wb.SheetNames.forEach(function (name, si) {
      if (si) doc.addPage();
      y = TOP;
      doc.setFont("helvetica", "bold"); doc.setFontSize(11); doc.setTextColor(M.INK[0], M.INK[1], M.INK[2]);
      doc.text(M.pdfText("Sheet: " + name), MG, y + 10); y += 20;
      var rows = XLSX.utils.sheet_to_json(wb.Sheets[name], { header: 1, raw: false, defval: "", blankrows: false });
      var nc = 0;
      rows.forEach(function (r) { for (var c = r.length - 1; c >= 0; c--) if (String(r[c]).trim() !== "") { nc = Math.max(nc, c + 1); break; } });
      if (!rows.length || !nc) { doc.setFont("helvetica", "normal"); doc.setFontSize(9); doc.text("(empty sheet)", MG, y + 8); return; }
      if (nc > MAXC) { notes.push("sheet " + name + ": first " + MAXC + " of " + nc + " columns"); nc = MAXC; }
      if (rows.length > MAXR) { notes.push("sheet " + name + ": first " + MAXR + " of " + rows.length + " rows"); rows = rows.slice(0, MAXR); }
      var len = []; for (var c = 0; c < nc; c++) len.push(3);
      rows.slice(0, 300).forEach(function (r) { for (var c = 0; c < nc; c++) len[c] = Math.max(len[c], Math.min(String(r[c] == null ? "" : r[c]).length, 36)); });
      var tot = len.reduce(function (a, b) { return a + b; }, 0), widths = len.map(function (l) { return l / tot * (W - 2 * MG); });
      var FS = nc > 14 ? 6 : nc > 8 ? 7 : 8, LH = FS * 1.25, PAD = 2.5;
      function row(r, head) {
        doc.setFont("helvetica", head ? "bold" : "normal"); doc.setFontSize(FS);
        var cl = widths.map(function (w, c) { return doc.splitTextToSize(M.pdfText(String(r[c] == null ? "" : r[c])), Math.max(w - 2 * PAD, 6)).slice(0, 6); });
        var h = Math.max.apply(null, cl.map(function (l) { return l.length || 1; })) * LH + 2 * PAD;
        return { cl: cl, h: h, head: head };
      }
      function draw(rw) {
        var x = MG;
        widths.forEach(function (w, c) {
          if (rw.head) { doc.setFillColor(233, 241, 236); doc.rect(x, y, w, rw.h, "F"); }
          doc.setDrawColor(200, 206, 212); doc.rect(x, y, w, rw.h, "S");
          doc.setFont("helvetica", rw.head ? "bold" : "normal"); doc.setFontSize(FS); doc.setTextColor(M.INK[0], M.INK[1], M.INK[2]);
          doc.text(rw.cl[c], x + PAD, y + PAD + FS);
          x += w;
        });
        y += rw.h;
      }
      var head = row(rows[0], true);
      draw(head);
      rows.slice(1).forEach(function (r) {
        var rw = row(r, false);
        if (y + rw.h > H - BOT) { doc.addPage(); y = TOP; draw(head); }
        draw(rw);
      });
    });
    return { bytes: doc.output("arraybuffer"), note: notes.join("; ") };
  }
  function preparePart(JsPDF, PDFLib, p) {
    var s = p.spec, ext = M.extOf(s.fileName);
    var fail = function (m) { return Promise.reject(new Error(m)); };
    if (!s.fileId) return fail("the document has no file");
    if (!s.canDownload) return fail("you don't have download access");
    if (s.size > EMBED_MAX) return fail("file is larger than " + M.fmtSize(EMBED_MAX) + "; open it from the widget");
    var kind = ext === "pdf" ? "pdf" : (ext === "docx" || ext === "docm") ? "docx" : /^(xlsx|xlsm|xlsb|xls|csv|ods)$/.test(ext) ? "sheet" : null;
    if (!kind) return fail(ext === "doc" ? "old .doc format can't be read in the browser (save it as .docx or PDF)" : "." + (ext || "?") + " files can't be shown in a PDF");
    var lib = kind === "docx" ? M.loadLib("mammoth") : kind === "sheet" ? M.loadLib("xlsx") : Promise.resolve();
    return lib.then(function () { return M.downloadTicket(s); }).then(fetchBytes).then(function (buf) {
      if (kind === "pdf") return buf;
      if (kind === "docx") return window.mammoth.convertToHtml({ arrayBuffer: buf }).then(function (res) { return renderHtmlPdf(JsPDF, res.value); })
        .then(function (r) { if (r.note) p.note = r.note; return r.bytes; });
      var r = renderSheetsPdf(JsPDF, window.XLSX, window.XLSX.read(new Uint8Array(buf), { type: "array" }));
      if (r.note) p.note = r.note;
      return r.bytes;
    }).then(function (bytes) {
      return PDFLib.PDFDocument.load(bytes, { ignoreEncryption: true }).catch(function (e) { throw new Error("the file is not a readable PDF (" + e.message + ")"); });
    }).then(function (src) {
      p.src = src; p.pages = src.getPageCount();
      if (!p.pages) throw new Error("the file has no pages");
    });
  }
  M.prepareParts = function (JsPDF, PDFLib, parts) {
    return parts.reduce(function (chain, p, i) {
      return chain.then(function () {
        M.setStatus("Preparing PDF… specification " + (i + 1) + " of " + parts.length + ": " + (p.spec.fileName || p.spec.docTitle));
        return preparePart(JsPDF, PDFLib, p).catch(function (e) { p.pages = 0; p.src = null; p.reason = e.message; });
      });
    }, Promise.resolve());
  };
  function fitText(font, text, size, maxW) {
    text = M.pdfText(text);
    if (font.widthOfTextAtSize(text, size) <= maxW) return text;
    while (text.length > 1 && font.widthOfTextAtSize(text + "...", size) > maxW) text = text.slice(0, -1);
    return text + "...";
  }
  // main report (jsPDF) + every spec page (scaled into a frame), then header/footer/watermark and links
  M.assemblePdf = function (JsPDF, PDFLib, v, parts) {
    var st = M.stamp(), mainN = 0, out = null;
    var appendixN = parts.reduce(function (a, p) { return a + (p.pages || 0); }, 0);
    for (var pass = 0; pass < 3; pass++) {          // the index lists page numbers, so the main page count must be stable
      var start = (out ? out.pages : M.buildPdf(JsPDF, v, { parts: parts, stamp: st, total: 999, pageOf: function () { return 999; } }).pages) + 1;
      parts.forEach(function (p) { if (p.pages) { p.first = start; start += p.pages; } });
      out = M.buildPdf(JsPDF, v, { parts: parts, stamp: st, total: start - 1, pageOf: function (p) { return p.first; } });
      if (out.pages + appendixN === start - 1) break;
    }
    mainN = out.pages;
    var N = mainN + appendixN, rgb = PDFLib.rgb, degrees = PDFLib.degrees;
    var RED = rgb(179 / 255, 38 / 255, 30 / 255), GREY = rgb(110 / 255, 120 / 255, 130 / 255), DARK = rgb(27 / 255, 39 / 255, 51 / 255);
    var final, font, bold;
    return PDFLib.PDFDocument.load(out.doc.output("arraybuffer")).then(function (d) {
      final = d;
      return Promise.all([final.embedFont(PDFLib.StandardFonts.Helvetica), final.embedFont(PDFLib.StandardFonts.HelveticaBold)]);
    }).then(function (f) {
      font = f[0]; bold = f[1];
      var pageNo = mainN;
      return parts.reduce(function (chain, p) {
        if (!p.src) return chain;
        return chain.then(function () { return final.embedPages(p.src.getPages()); }).then(function (embs) {
          p.src.getPages().forEach(function (sp, k) {
            var rot = ((sp.getRotation().angle % 360) + 360) % 360, sz = sp.getSize();
            var dw = rot % 180 ? sz.height : sz.width, dh = rot % 180 ? sz.width : sz.height;
            var PW = dw, PH = dh, TOPB = 30, BOTB = 24, SIDE = 14;
            if (PW < 300 || PH < 300) { var up = 612 / Math.min(PW, PH); PW *= up; PH *= up; }
            var s = Math.min((PW - 2 * SIDE) / dw, (PH - TOPB - BOTB) / dh);
            var cw = dw * s, ch = dh * s, x0 = (PW - cw) / 2, y0 = BOTB + ((PH - TOPB - BOTB) - ch) / 2;
            var page = final.addPage([PW, PH]);
            var o = rot === 90 ? { x: x0, y: y0 + ch, rotate: degrees(-90) } : rot === 180 ? { x: x0 + cw, y: y0 + ch, rotate: degrees(180) } :
                    rot === 270 ? { x: x0 + cw, y: y0, rotate: degrees(90) } : { x: x0, y: y0 };
            o.xScale = s; o.yScale = s;
            page.drawPage(embs[k], o);
            page.drawRectangle({ x: x0, y: y0, width: cw, height: ch, borderColor: rgb(0.8, 0.82, 0.85), borderWidth: 0.6 });
            pageNo++;
            // header: which spec, which item; footer like the main report
            var left = "A" + p.no + "  Specification: " + (p.spec.fileName || p.spec.docTitle) + "  (" + p.spec.docName + (p.spec.rev !== "" ? ", rev " + p.spec.rev : "") + ")";
            var right = "attached to " + p.items.join(", ") + "   -   page " + (k + 1) + " of " + p.pages;
            var rw = font.widthOfTextAtSize(M.pdfText(right), 7.5);
            page.drawText(fitText(bold, left, 8, PW - 2 * SIDE - Math.min(rw, PW * 0.45) - 12), { x: SIDE, y: PH - 18, size: 8, font: bold, color: DARK });
            page.drawText(fitText(font, right, 7.5, PW * 0.45), { x: PW - SIDE - Math.min(rw, PW * 0.45), y: PH - 18, size: 7.5, font: font, color: GREY });
            page.drawLine({ start: { x: SIDE, y: PH - 23 }, end: { x: PW - SIDE, y: PH - 23 }, thickness: 0.5, color: rgb(0.82, 0.82, 0.82) });
            page.drawText("DRAFT - not released", { x: SIDE, y: 9, size: 8, font: font, color: GREY });
            var pn = "Page " + pageNo + " of " + N;
            page.drawText(pn, { x: PW - SIDE - font.widthOfTextAtSize(pn, 8), y: 9, size: 8, font: font, color: GREY });
            var size = 150 * Math.min(PW / 792, PH / 612), tw = bold.widthOfTextAtSize("DRAFT", size), a = Math.PI / 6;
            page.drawText("DRAFT", { x: PW / 2 - (tw / 2) * Math.cos(a), y: PH / 2 - (tw / 2) * Math.sin(a) - size * 0.3, size: size, font: bold,
                                     color: RED, opacity: 0.13, rotate: degrees(30) });
          });
        });
      }, Promise.resolve());
    }).then(function () {
      // clickable spec names / index rows -> first page of that appendix section
      var H = out.H;
      out.links.forEach(function (l) {
        if (!l.part.first) return;
        var annot = final.context.obj({ Type: "Annot", Subtype: "Link", Rect: [l.x, H - l.y - l.h, l.x + l.w, H - l.y],
                                        Border: [0, 0, 0], Dest: [final.getPage(l.part.first - 1).ref, "Fit"] });
        final.getPage(l.page - 1).node.addAnnot(final.context.register(annot));
      });
      final.setTitle(M.pdfText((v.item.title || v.item.name) + " - DRAFT"));
      final.setProducer("Mfg Item Viewer v" + M.version);
      return final.save();
    }).then(function (bytes) { return { bytes: bytes, file: out.file, pages: N, mainPages: mainN }; });
  };
})(window.MFV);
