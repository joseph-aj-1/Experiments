/*
 * Mfg Item Viewer - export: the "Export PDF" button flow (wait for MEI/spec lookups,
 * build the report, add the specification appendix, save).
 */
(function (M) {
  "use strict";

  var exporting = false;
  M.exportPdf = function () {
    var v = M.app.view;
    if (!v || exporting) return;
    exporting = true;
    M.setStatus("Preparing PDF…");
    var pending = [v.meiPromise, v.specPromise].filter(Boolean);
    var waitAll = Promise.race([Promise.all(pending), new Promise(function (r) { setTimeout(r, 20000); })]);
    waitAll.then(M.loadJsPDF).then(function (JsPDF) {
      if (v !== M.app.view) throw new Error("The displayed item changed; click Export PDF again.");
      var parts = M.specPartsFor(v);
      if (!parts.length) {
        var out = M.buildPdf(JsPDF, v);
        window.__lastPdf = out;
        out.doc.save(out.file);
        return M.setStatus("PDF saved: " + out.file);
      }
      return M.loadLib("pdflib").then(function (PDFLib) {
        return M.prepareParts(JsPDF, PDFLib, parts).then(function () {
          M.setStatus("Preparing PDF… merging " + parts.length + " specification" + (parts.length === 1 ? "" : "s"));
          return M.assemblePdf(JsPDF, PDFLib, v, parts);
        }).then(function (r) {
          window.__lastPdf = r; window.__lastParts = parts;
          M.saveBytes(r.bytes, r.file);
          var missing = parts.filter(function (p) { return !p.pages; }).length;
          M.setStatus("PDF saved: " + r.file + " — " + (parts.length - missing) + " of " + parts.length + " specification" + (parts.length === 1 ? "" : "s") +
                    " included" + (missing ? " (see the appendix list for why the others are not)" : ""), false);
        });
      }, function (e) {           // merge library unavailable: report + appendix list only
        parts.forEach(function (p) { p.pages = 0; p.reason = "the PDF merge library could not be downloaded"; });
        var out = M.buildPdf(JsPDF, v, { parts: parts });
        window.__lastPdf = out;
        out.doc.save(out.file);
        M.setStatus("PDF saved without specification contents: " + e.message, true);
      });
    }).catch(function (e) {
      if (/PDF library/.test(e.message)) {
        try { M.printFallback(v); M.setStatus(e.message + " Opened a printable version instead (choose “Save as PDF”).", true); }
        catch (printErr) { M.setStatus(e.message + " " + printErr.message, true); }
      } else M.setStatus("PDF export failed: " + e.message, true);
    }).then(function () { exporting = false; });
  };
})(window.MFV);
