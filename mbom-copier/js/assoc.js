/*
 * MBOM Copier - assoc: associated objects of every item in the structure, read from this
 * (source) tenant with the signed-in user's session, for the kinds the user ticks:
 *   changeActions  change impact (dslc) + change action details
 *   plants         Manufacturing Responsibility links (dsmfg) + plant names
 *   meis           Equivalent Qualifications (Sourcing, dssrc) + MEI details
 *   specs          Specification Documents with their files (Document web services)
 * Shown in the preview's Associated column and sent with the dry run; the service on the PC
 * re-creates them in the target. Spec files are downloaded here and handed to the service.
 *
 * M.src.assoc = { options, items: { itemId: { kind: [...] } }, meis: {}, docs: {}, changeActions: {} }
 */
(function (M) {
  "use strict";
  var MFG = "/resources/v1/modeler/dsmfg/dsmfg:MfgItem/";
  var DOCS = "/resources/v1/modeler/documents";
  M.ASSOC_KINDS = [
    { key: "changeActions", label: "Change Actions", short: "CA" },
    { key: "plants", label: "Plants", short: "Plant", title: "Plants linked through Manufacturing Responsibility" },
    { key: "meis", label: "MEIs", short: "MEI", title: "Manufacturer Equivalent Items (Equivalent Qualifications)" },
    { key: "specs", label: "Specifications", short: "Spec", title: "Specification documents with their files" }
  ];

  // ---------- which kinds are ticked (kept in this browser) ----------
  M.assocOptions = function () {
    var o = {};
    M.ASSOC_KINDS.forEach(function (k) { o[k.key] = !!(M.ui.assoc[k.key] && M.ui.assoc[k.key].checked); });
    return o;
  };
  M.saveAssocOptions = function () {
    try { window.localStorage.setItem("mbc.assoc", JSON.stringify(M.assocOptions())); } catch (noStorage) { /* not kept */ }
  };
  M.savedAssocOptions = function () {
    try { return JSON.parse(window.localStorage.getItem("mbc.assoc") || "{}") || {}; } catch (noStorage) { return {}; }
  };

  // ---------- platform helpers ----------
  function csrfHeader(base) {
    return M.request("GET", base + "/resources/v1/application/CSRF", null, false).then(function (r) {
      var c = (r && r.csrf) || {};
      if (!c.value) throw new Error("No CSRF token from " + base + ".");
      var h = {}; h[c.name || "ENO_CSRF_TOKEN"] = c.value;
      return h;
    });
  }
  M.findSourcing = function () {
    if (M.app.sourcingP) return M.app.sourcingP;
    M.app.sourcingP = new Promise(function (resolve) {
      var fallback = /-space\./.test(M.app.space) ? M.app.space.replace("-space.", "-sourcing.") : null;
      try {
        M.Compass.getServiceUrl({
          serviceName: "Sourcing", platformId: M.app.tenant,
          onComplete: function (u) { var v = Array.isArray(u) ? (u[0] && u[0].url) : u; resolve(v ? String(v).replace(/\/$/, "") : fallback); },
          onFailure: function () { resolve(fallback); }
        });
      } catch (noRegistry) { resolve(fallback); }
    });
    return M.app.sourcingP;
  };
  function members(r) { return M.members(r); }
  function idOf(x) { return x && (x.id || x.identifier || String(x.relativePath || "").split("/").pop()); }

  // ---------- readers (one per kind); each fills A for all ids ----------
  var READ = {};

  READ.specs = function (ids, A) {
    return M.mapLimit(ids, 6, function (id) {
      return M.get(DOCS + "/parentId/" + encodeURIComponent(id) + "?parentRelName=SpecificationDocument&include=files").then(function (resp) {
        var r = resp && (resp.result || resp), list = (r && r.data) || [];
        A.items[id].specs = list.map(function (d) {
          var de = d.dataelements || {};
          A.docs[d.id] = { id: d.id, type: d.type || "Document", name: de.name || "", title: de.title || de.name || "", revision: de.revision || "",
                           description: de.description || "", state: de.stateNLS || de.state || "",
                           files: ((d.relateddata && d.relateddata.files) || []).map(function (f) {
                             var fe = f.dataelements || {};
                             return { id: f.id, name: fe.title || de.title || f.id, size: +fe.fileSize || 0 };
                           }) };
          return d.id;
        });
      });
    }).then(failures("specifications"));
  };

  READ.plants = function (ids, A) {
    var names = {};
    return M.mapLimit(ids, 6, function (id) {
      return M.get(MFG + encodeURIComponent(id) + "/dsmfg:MfgResponsibility?$mask=dsmfg:MfgResponsibilityMask.Details").then(function (r) {
        A.items[id].plants = members(r).map(function (l) {
          var o = l.organizationRef || {}, pid = idOf(o);
          var attrs = l["dsmfg:MfgResponsibilityEnterpriseAttributes"] || null;
          names[pid] = names[pid] || o.relativePath || ("/resources/v1/modeler/organizations/" + pid);
          var mob = /^undefined$/i.test(l.makeOrBuy || "") ? "" : (l.makeOrBuy || "");
          return { id: pid, link: l.id, makeOrBuy: mob, attributes: attrs, name: null };
        });
      });
    }).then(failures("plants")).then(function () {
      // plant names: read through the organization's own resource path
      return M.mapLimit(Object.keys(names), 4, function (pid) {
        return M.get(names[pid]).then(function (r) {
          var m = members(r)[0] || ((r && (r.data || (r.result && r.result.data))) || [])[0] || r || {};
          var de = m.dataelements || m;
          return de.title || de.name || de.displayName || null;
        }, function () { return null; });
      }).then(function (list) {
        var byId = {};
        Object.keys(names).forEach(function (pid, k) { byId[pid] = list[k]; });
        Object.keys(A.items).forEach(function (id) {
          (A.items[id].plants || []).forEach(function (p) { p.name = byId[p.id] || null; });
        });
      });
    });
  };

  var QUAL_TYPES = { "SRC Manufacturing Equivalent Qualification": "manufacturingEquivalentQualification",
                     "Manufacturing Equivalent Qualification": "manufacturingEquivalentQualification",
                     "Engineering Equivalent Qualification": "equivalentQualification" };
  READ.meis = function (ids, A) {
    return M.findSourcing().then(function (sourcing) {
      if (!sourcing) throw new Error("the Sourcing service is not available on this tenant");
      var batches = [];
      for (var i = 0; i < ids.length; i += 20) batches.push(ids.slice(i, i + 20));
      return csrfHeader(sourcing).then(function (hdr) {
        return Promise.all(batches.map(function (batch) {
          var body = { data: batch.map(function (id) {
            return { id: id, identifier: id, source: M.app.space, relativePath: MFG + id };
          }) };
          return M.request("POST", sourcing + "/resources/v1/modeler/dssrc/qualifications/contextLocate" +
                           "?type=equivalentQualification&$include=target,contexts", body, true, hdr).then(function (resp) {
            var r = (resp && (resp.result || resp)) || {};
            (r.data || []).forEach(function (q) {
              var mid = idOf(q.target);
              if (!mid) return;
              A.meis[mid] = A.meis[mid] || { id: mid };
              (q.context || q.contexts || []).forEach(function (c) {
                var cid = idOf(c);
                if (!A.items[cid]) return;
                (A.items[cid].meis = A.items[cid].meis || []).push({ mei: mid, qualification: {
                  apiType: QUAL_TYPES[q.type] || "manufacturingEquivalentQualification", type: q.type, name: q.name, title: q.title,
                  state: q.state, preferred: q.preferred, approved: q.approved, description: q.description || "",
                  comments: q.comments || "", restriction: q.restriction || q.Restriction || "" } });
              });
            });
          });
        }));
      });
    }).then(function () {
      ids.forEach(function (id) { A.items[id].meis = A.items[id].meis || []; });
      return M.mapLimit(Object.keys(A.meis), 4, function (mid) { return meiDetails(mid, A.meis[mid]); });
    });
  };
  function meiDetails(id, out) {
    var SRC = "/resources/v1/modeler/dssrc/dssrc:ManufacturerEquivalentItems/";
    return Promise.all([
      M.get(SRC + encodeURIComponent(id)).then(function (r) {
        var m = members(r)[0] || {};
        out.mpn = m.manufacturerPartNumber; out.partSource = m.partSource; out.partSourceURL = m.partSourceURL;
        if (m.manufacturerCompany) out.manufacturerCompany = m.manufacturerCompany;
        if (m.manufacturer) out.manufacturer = m.manufacturer;
      }, function () {}),
      M.get("/resources/v1/modeler/dseng/dseng:EngItem/" + encodeURIComponent(id)).then(function (r) {
        var m = members(r)[0] || {}; out.title = m.title; out.name = m.name; out.revision = m.revision;
      }, function () {})
    ]).then(function () {
      var q = out.mpn || out.title || out.name;
      if (!q || out.manufacturer) return;
      return M.get(SRC + "search?$searchStr=" + encodeURIComponent(q) + "&$mask=dsmvsrc:ManufacturerEquivalentItem.Details&$top=50")
        .then(function (r) {
          var hit = members(r).filter(function (m) { return m.id === id; })[0];
          if (hit) { out.manufacturer = hit.manufacturer; out.mpn = out.mpn || hit.manufacturerPartNumber; out.title = out.title || hit.title; }
        }, function () {});
    });
  }

  READ.changeActions = function (ids, A) {
    return M.mapLimit(ids, 6, function (id) {
      return M.get(MFG + encodeURIComponent(id) + "/dslc:changeImpact").then(function (r) {
        var list = [];
        members(r).forEach(function (m) {
          (m["Impacting Objects"] || m.impactingObjects || []).forEach(function (o) {
            var ro = o.referencedObject || {};
            if (!/change action/i.test(ro.type || "Change Action")) return;
            var cid = idOf(ro);
            if (cid && !list.some(function (x) { return x.id === cid; })) list.push({ id: cid, impact: o.impactType || "" });
          });
        });
        A.items[id].changeActions = list;
        list.forEach(function (c) { A.changeActions[c.id] = A.changeActions[c.id] || { id: c.id }; });
        // "Change Required" on the item (change control): NONE, ANY, ID or MANY
        return M.get(MFG + encodeURIComponent(id) + "/dslc:changeControl").then(function (cr) {
          var m = members(cr)[0] || {};
          A.items[id].changeControl = { status: m["Change Control Status"] || "NONE",
                                        controlling: (m["Controlling Changes"] || []).map(idOf) };
        }, function () { /* not readable: leave it unknown */ });
      });
    }).then(failures("change actions")).then(function () {
      return M.mapLimit(Object.keys(A.changeActions), 4, function (cid) {
        return M.get("/resources/v1/modeler/dslc/changeaction/" + encodeURIComponent(cid)).then(function (r) {
          var ca = (r && (r.member ? members(r)[0] : r)) || {};
          var o = A.changeActions[cid];
          ["name", "title", "description", "severity", "state", "type", "policy"].forEach(function (k) { if (ca[k]) o[k] = ca[k]; });
        }, function () {});
      });
    });
  };

  // a reader that tolerates some failing items, but not all of them
  function failures(what) {
    return function (res) {
      var bad = res.filter(function (x) { return x && x.error; });
      if (bad.length && bad.length === res.length) throw bad[0].error;
      if (bad.length) M.assocNote = (M.assocNote || []).concat(bad.length + " item(s): " + what + " could not be read");
      return res;
    };
  }

  // ---------- load the ticked kinds that are not loaded yet ----------
  M.loadAssoc = function (seq) {
    var src = M.src;
    if (!src) return Promise.resolve();
    var want = M.assocOptions();
    src.assoc = src.assoc || { options: {}, items: {}, meis: {}, docs: {}, changeActions: {} };
    src.assocState = src.assocState || {};
    var ids = Object.keys(src.items);
    ids.forEach(function (id) { src.assoc.items[id] = src.assoc.items[id] || {}; });
    var todo = M.ASSOC_KINDS.filter(function (k) { return want[k.key] && !src.assocState[k.key]; });
    if (!todo.length) { M.renderAssocNote(); return Promise.resolve(); }
    todo.forEach(function (k) { src.assocState[k.key] = "loading"; });
    M.renderAssocNote();
    return Promise.all(todo.map(function (k) {
      return READ[k.key](ids, src.assoc).then(function () { src.assocState[k.key] = "ok"; },
        function (e) { src.assocState[k.key] = "error: " + (e && e.message || e); });
    })).then(function () {
      if (seq !== undefined && seq !== M.loadSeq) return;
      M.renderAssocNote();
      if (!M.plan) M.renderTable(M.previewRows(src));
    });
  };

  // what is sent with the dry run: only the ticked kinds, only what was read
  M.assocPayload = function () {
    var src = M.src, opt = M.assocOptions(), out = { options: {}, items: {}, meis: {}, docs: {}, changeActions: {} };
    if (!src || !src.assoc) return null;
    M.ASSOC_KINDS.forEach(function (k) { out.options[k.key] = !!(opt[k.key] && src.assocState[k.key] === "ok"); });
    if (!M.ASSOC_KINDS.some(function (k) { return out.options[k.key]; })) return null;
    Object.keys(src.assoc.items).forEach(function (id) {
      var a = src.assoc.items[id], o = {};
      M.ASSOC_KINDS.forEach(function (k) { if (out.options[k.key] && a[k.key] && a[k.key].length) o[k.key] = a[k.key]; });
      if (out.options.changeActions && a.changeControl) o.changeControl = a.changeControl;
      if (Object.keys(o).length) out.items[id] = o;
    });
    if (out.options.meis) out.meis = src.assoc.meis;
    if (out.options.specs) out.docs = src.assoc.docs;
    if (out.options.changeActions) out.changeActions = src.assoc.changeActions;
    return out;
  };

  // badges for the preview (before a dry run)
  M.previewBadges = function (id) {
    var src = M.src, opt = M.assocOptions(), a = src && src.assoc && src.assoc.items[id];
    if (!a) return [];
    var out = [];
    M.ASSOC_KINDS.forEach(function (k) {
      if (!opt[k.key]) return;
      (a[k.key] || []).forEach(function (e) {
        var label;
        if (k.key === "specs") {
          var d = src.assoc.docs[e] || {};
          label = (d.title || d.name || e) + (d.files && d.files.length ? " — " + d.files.map(function (f) { return f.name; }).join(", ") : "");
        } else if (k.key === "plants") {
          label = (e.name || "plant " + e.id.slice(0, 8) + "…") + (e.makeOrBuy ? " (" + e.makeOrBuy + ")" : "");
        } else if (k.key === "meis") {
          var m = src.assoc.meis[e.mei] || {};
          label = [m.manufacturer, m.mpn || m.title].filter(Boolean).join(" · ") +
                  (String(e.qualification.preferred).toUpperCase() === "TRUE" ? " (preferred)" : "");
        } else {
          var c = src.assoc.changeActions[e.id] || {};
          label = (c.name || e.id) + (c.title && c.title !== c.name ? " " + c.title : "") + (e.impact ? " (" + String(e.impact).toLowerCase() + ")" : "");
        }
        out.push({ kind: k.key, label: label, action: "", status: "" });
      });
    });
    return out;
  };

  M.renderAssocNote = function () {
    var src = M.src, ui = M.ui, parts = [];
    if (!src || !src.assocState) { ui.assocNote.textContent = ""; return; }
    var opt = M.assocOptions();
    M.ASSOC_KINDS.forEach(function (k) {
      if (!opt[k.key]) return;
      var st = src.assocState[k.key];
      if (st === "loading") parts.push(k.label + ": reading…");
      else if (st && st.indexOf("error") === 0) parts.push(k.label + ": could not be read (" + st.slice(7) + ")");
      else if (st === "ok") {
        var objs = {}, on = 0;
        Object.keys(src.assoc.items).forEach(function (id) {
          var list = src.assoc.items[id][k.key] || [];
          if (list.length) on++;
          list.forEach(function (e) { objs[typeof e === "string" ? e : (e.id || e.mei)] = true; });
        });
        var n = Object.keys(objs).length;
        parts.push(k.label + ": " + n + (n ? " on " + on + " item" + (on === 1 ? "" : "s") : ""));
      }
    });
    ui.assocNote.textContent = parts.join(" · ") + (M.assocNote && M.assocNote.length ? " · " + M.assocNote.join("; ") : "");
    ui.assocNote.className = "assocnote" + (parts.some(function (p) { return p.indexOf("could not") >= 0; }) ? " error" : "");
  };

  // ---------- spec files: source -> service ----------
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
  function toBase64(buf) {
    var bytes = new Uint8Array(buf), out = [], CH = 0x8000;
    for (var i = 0; i < bytes.length; i += CH) out.push(String.fromCharCode.apply(null, bytes.subarray(i, i + CH)));
    return btoa(out.join(""));
  }
  var MAX_FILE = 35 * 1024 * 1024;
  M.sendFiles = function (run, list) {
    var n = 0;
    return csrfHeader(M.app.space).then(function (hdr) {
      return list.reduce(function (chain, f) {
        return chain.then(function () {
          n++;
          M.setStatus("Copying specification files… " + n + " of " + list.length + " (" + (f.name || f.file) + ")");
          if (f.size > MAX_FILE) throw new Error(f.name + " is larger than 35 MB; the widget can't carry it");
          return M.request("PUT", M.app.space + DOCS + "/" + encodeURIComponent(f.doc) + "/files/" + encodeURIComponent(f.file) +
                           "/DownloadTicket", null, true, hdr).then(function (resp) {
            var r = resp && (resp.result || resp), d = ((r && r.data) || [])[0], u = d && d.dataelements && d.dataelements.ticketURL;
            if (!u) throw new Error("no download ticket for " + f.name);
            return fetchBytes(u);
          }).then(function (buf) {
            return M.svc("POST", "/runs/" + encodeURIComponent(run) + "/files", { file: f.file, data: toBase64(buf) });
          }).catch(function (e) { throw new Error("Specification file " + (f.name || f.file) + ": " + e.message); });
        });
      }, Promise.resolve());
    });
  };
})(window.MBC);
