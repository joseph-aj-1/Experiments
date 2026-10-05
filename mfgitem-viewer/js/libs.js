/*
 * Mfg Item Viewer - libs: third-party libraries, loaded only when first needed.
 * Copies are served with the widget (vendor/, GitHub Pages); public CDNs are the backup.
 * The dashboard's AMD loader (define/require) is hidden while a library loads, otherwise
 * the UMD builds would register as anonymous AMD modules instead of setting their global.
 */
(function (M) {
  "use strict";
  var LIBS = {
    jspdf:   { g: "jspdf",   name: "PDF library",       file: "jspdf.umd.min.js",
               cdn: ["https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js",
                     "https://cdn.jsdelivr.net/npm/jspdf@2.5.1/dist/jspdf.umd.min.js"] },
    pdflib:  { g: "PDFLib",  name: "PDF merge library", file: "pdf-lib.min.js",
               cdn: ["https://cdnjs.cloudflare.com/ajax/libs/pdf-lib/1.17.1/pdf-lib.min.js",
                     "https://cdn.jsdelivr.net/npm/pdf-lib@1.17.1/dist/pdf-lib.min.js"] },
    mammoth: { g: "mammoth", name: "Word reader",       file: "mammoth.browser.min.js",
               cdn: ["https://cdn.jsdelivr.net/npm/mammoth@1.8.0/mammoth.browser.min.js"] },
    xlsx:    { g: "XLSX",    name: "Excel reader",      file: "xlsx.full.min.js",
               cdn: ["https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js",
                     "https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js"] }
  };
  var scriptChain = Promise.resolve();      // one library at a time, so define/require are restored correctly

  function injectScript(url, g) {
    return new Promise(function (resolve, reject) {
      var savedDefine = window.define, savedRequire = window.require;
      window.define = undefined; window.require = undefined;
      var sc = document.createElement("script");
      sc.src = url; sc.async = true; sc.crossOrigin = "anonymous";
      var done = function (ok) {
        window.define = savedDefine; window.require = savedRequire; sc.onload = sc.onerror = null;
        if (ok && window[g]) resolve(window[g]); else reject(new Error("failed: " + url));
      };
      sc.onload = function () { done(true); };
      sc.onerror = function () { done(false); };
      (document.head || document.documentElement).appendChild(sc);
    });
  }

  M.loadLib = function (key) {
    var L = LIBS[key];
    if (window[L.g]) return Promise.resolve(window[L.g]);
    if (!L.p) {
      var urls = [M.base + "vendor/" + L.file + "?v=" + encodeURIComponent(M.version)].concat(L.cdn);
      var tryUrls = function (i) {
        if (window[L.g]) return Promise.resolve(window[L.g]);
        if (i >= urls.length) return Promise.reject(new Error("Could not download the " + L.name + " (GitHub Pages and the CDNs were not reachable)."));
        return injectScript(urls[i], L.g).catch(function () { return tryUrls(i + 1); });
      };
      L.p = scriptChain = scriptChain.then(function () { return tryUrls(0); }, function () { return tryUrls(0); });
      L.p.catch(function () { L.p = null; });
    }
    return L.p;
  };
  M.loadJsPDF = function () { return M.loadLib("jspdf").then(function (m) { return m.jsPDF; }); };
})(window.MFV);
