/*
 * Mfg Item Viewer - specs: documents attached with a "Specification Document" link
 * (Document Web Services, relationship SpecificationDocument). Fills the BOM table's
 * Specification column; clicking a file opens it through a short-lived FCS download ticket.
 */
(function (M) {
  "use strict";
  var esc = M.esc;
  var DOCS = "/resources/v1/modeler/documents";
  var SPEC_REL = "SpecificationDocument";
  M.specIndex = {};       // "docId|fileId" -> spec record (for clicks and the PDF appendix)

  function specsFor(id) {
    return M.get(DOCS + "/parentId/" + encodeURIComponent(id) + "?parentRelName=" + encodeURIComponent(SPEC_REL) + "&include=files")
      .then(function (resp) {
        var out = [];
        M.docData(resp).forEach(function (d) {
          var de = d.dataelements || {}, files = (d.relateddata && d.relateddata.files) || [];
          var base = { docId: d.id, docTitle: de.title || de.name || "", docName: de.name || "", rev: de.revision || "",
                       state: de.stateNLS || de.state || "", canDownload: de.hasDownloadAccess !== "FALSE" };
          if (!files.length) out.push(Object.assign({ fileId: null, fileName: "", size: 0, key: d.id + "|" }, base));
          files.forEach(function (f) {
            var fe = f.dataelements || {};
            out.push(Object.assign({ fileId: f.id, fileName: fe.title || base.docTitle, size: +fe.fileSize || 0, key: d.id + "|" + f.id }, base));
          });
        });
        out.forEach(function (s) { M.specIndex[s.key] = s; });
        return out;
      });
  }

  var spaceCsrfP = null;
  function spaceCsrf(fresh) {
    if (fresh || !spaceCsrfP) {
      spaceCsrfP = M.request("GET", M.app.space + "/resources/v1/application/CSRF", null, false).then(function (r) {
        var c = (r && r.csrf) || {};
        if (!c.value) throw new Error("No CSRF token from 3DSpace.");
        return c;
      });
      spaceCsrfP.catch(function () { spaceCsrfP = null; });
    }
    return spaceCsrfP;
  }
  // FCS download URL for one file (short-lived, so requested on every click/export)
  M.downloadTicket = function (s, retried) {
    return spaceCsrf(retried).then(function (csrf) {
      var hdr = {}; hdr[csrf.name || "ENO_CSRF_TOKEN"] = csrf.value;
      return M.request("PUT", M.app.space + DOCS + "/" + encodeURIComponent(s.docId) + "/files/" + encodeURIComponent(s.fileId) + "/DownloadTicket", null, true, hdr);
    }).then(function (resp) {
      var d = M.docData(resp)[0], u = d && d.dataelements && d.dataelements.ticketURL;
      if (!u) throw new Error("3DSpace returned no download ticket for " + (s.fileName || s.docTitle) + ".");
      return u;
    }, function (e) { if (!retried) return M.downloadTicket(s, true); throw e; });
  };

  M.openSpec = function (s, link) {
    if (!s || !s.fileId) return;
    // open the tab now (inside the click) so pop-up blockers allow it, then point it at the file
    var win = null;
    try { win = window.open("", "_blank"); } catch (ignored) { win = null; }
    if (link) link.className += " busy";
    M.setStatus("Opening " + s.fileName + "…");
    M.downloadTicket(s).then(function (u) {
      if (win && !win.closed) win.location.href = u;
      else { var a = M.el("a"); a.href = u; a.target = "_blank"; a.rel = "noopener"; document.body.appendChild(a); a.click(); a.remove(); }
      M.setStatus("");
    }).catch(function (e) {
      try { if (win) win.close(); } catch (ignored) { /* already closed */ }
      M.setStatus("Could not open " + s.fileName + ": " + e.message, true);
    }).then(function () { if (link) link.className = link.className.replace(/\s*busy/g, ""); });
  };

  function specLinks(list) {
    if (!list.length) return "<span class='none'>—</span>";
    return list.map(function (s) {
      if (!s.fileId) return "<span class='none' title='" + esc(s.docName) + "'>" + esc(s.docTitle) + " (no file)</span>";
      var ext = M.extOf(s.fileName);
      var tip = s.docTitle + " · " + s.docName + (s.rev !== "" ? " · Rev " + s.rev : "") + (s.state ? " · " + s.state : "") + (s.size ? " · " + M.fmtSize(s.size) : "");
      return "<a class='spec' href='#' data-spec='" + esc(s.key) + "' title='" + esc(tip) + "'>" +
             (ext ? "<span class='ext " + esc(ext) + "'>" + esc(ext.toUpperCase()) + "</span>" : "") + esc(s.fileName) + "</a>";
    }).join("<br/>");
  }
  function setSpecCells(id, html) {
    Array.prototype.forEach.call(M.ui.details.querySelectorAll("tr[data-mid='" + id + "']"), function (tr) {
      var c = tr.querySelector(".sc"); if (c) c.innerHTML = html;
    });
  }
  function specSummary(text, isError) {
    var e = M.ui.details.querySelector(".specsum");
    if (e) { e.textContent = text; e.className = "sub specsum" + (isError ? " error" : ""); }
  }

  M.loadSpecs = function (item, bomRows, seq) {
    var ids = M.tableItemIds(item, bomRows), view = M.app.view;
    var p = M.mapLimit(ids, 6, specsFor).then(function (results) {
      if (seq !== M.loadSeq) return;
      var files = 0, withSpec = 0, failed = 0;
      ids.forEach(function (id, k) {
        var r = results[k];
        if (!r || r.error) { failed++; setSpecCells(id, "<span class='none' title='" + esc(r && r.error && r.error.message) + "'>(error)</span>"); return; }
        if (view) view.specs[id] = r;
        if (r.length) withSpec++;
        files += r.filter(function (s) { return s.fileId; }).length;
        setSpecCells(id, specLinks(r));
      });
      var text = "Specifications: " + files + " file" + (files === 1 ? "" : "s") + " on " + withSpec + " of " + ids.length +
                 " item" + (ids.length === 1 ? "" : "s") + (failed ? " (" + failed + " could not be read)" : "");
      specSummary(text, failed === ids.length);
      if (view) { view.specText = text; view.specDone = true; }
    });
    if (view) view.specPromise = p.then(function () {}, function () {});
  };
})(window.MFV);
