"""Associated objects for the MBOM copy: Change Actions, Plants (Manufacturing Responsibility),
Manufacturer Equivalent Items (MEIs) and Specification documents.

The widget reads them from the source with the dashboard sign-in and sends them with the
structure (rec["assoc_in"]). This module plans and re-creates them in the target, for the
items the copy creates. Items that are reused from the target keep what they already have.

    Change Actions   one new CA per source CA (title, description, severity); the copied items
                     it impacted are added as proposed changes. State and approvals start fresh.
    Plants           matched by name in the target and linked with the same Make/Buy;
                     a plant missing in the target is reported and its links are skipped.
    MEIs             reused when the target has one with the same manufacturer and part number,
                     created otherwise; a Manufacturing Equivalent Qualification links it to the
                     copied item with the same preferred / approved values.
    Specifications   each document is created once in the target with its files (latest version)
                     and attached as Specification Document to every copied item that had it.

State lives in rec["assoc"] and is saved after every step, like the MBOM itself, so a stopped
copy resumes without creating anything twice.
"""
from __future__ import annotations

import asyncio
import base64
import re
from pathlib import Path

import httpx

KINDS = ("specs", "plants", "meis", "changeActions")
LABEL = {"specs": "Specification", "plants": "Plant", "meis": "MEI", "changeActions": "Change Action"}
MFG_REL = "/resources/v1/modeler/dsmfg/dsmfg:MfgItem/{}"
MEI_REL = "/resources/v1/modeler/dssrc/dssrc:ManufacturerEquivalentItems/{}"
ORG_REL = "/resources/v1/modeler/organizations/{}"
DOC_REL = "/resources/v1/modeler/documents/{}"
CA_REL = "/resources/v1/modeler/dslc/changeaction/{}"

# Web services per target client (OpenAPI "servers" blocks, as in tdx-mcp-server/specs).
SERVICES = {
    "mei": [("3DSpace", "{3DSpace}/resources/v1/modeler/dssrc"),
            ("APIGateway", "{APIGateway}/api/dssrc-manufacturerEquivalentItems/v1")],
    "qual": [("Sourcing", "{Sourcing}/resources/v1/modeler/dssrc"),
             ("APIGateway", "{APIGateway}/api/dssrc-qualifications/v1")],
    "docs": [("3DSpace", "{3DSpace}/resources/v1/modeler/documents"),
             ("APIGateway", "{APIGateway}/api/documents/v1")],
    # Change Action Web Services 1.13 (tdx-mcp-server/specs/ChangeAction.json)
    "ca": [("3DSpace", "{3DSpace}/resources/v1/modeler/dslc"),
           ("APIGateway", "{APIGateway}/api/dslc:CA/v1")],
    # plant lookup (read-only): the organizations resource the responsibility links point to,
    # then 3DSearch, the service behind the dashboard's search box
    "org": [("3DSpace", "{3DSpace}/resources/v1/modeler")],
    "search": [("fedsearch", "{fedsearch}/federated")],
}

# Not yet confirmed against the official OpenAPI specs: writes stay off until they are.
CA_API = {"confirmed": True,
          # how a copied item is added to the new CA: work on its current (In Work) version
          "target": "CurrentVersion", "what": "Modify", "batch": 150}
PLANT_API = {"confirmed": True}


class Pending(RuntimeError):
    """A web service whose spec is not confirmed yet."""


def ref(source: str, rel: str, ident: str, typ: str = "") -> dict:
    out = {"source": source, "identifier": ident, "relativePath": rel.format(ident), "id": ident}
    if typ:
        out["type"] = typ
    return out


def yes_no(v) -> str:
    return "Yes" if str(v).strip().upper() in ("TRUE", "YES", "Y", "1") else "No"


def norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


class Associations:
    def __init__(self, copier, client_for, space_url: str, file_dir: Path, fcs_client=None):
        """client_for(service) -> mbom_copy.Api for that web service in the target."""
        self.cp, self.client_for, self.space = copier, client_for, space_url.rstrip("/")
        self.file_dir, self._fcs = Path(file_dir), fcs_client
        self.inp = copier.rec.get("assoc_in") or {}
        self.st = copier.rec.setdefault("assoc", {"plants": {}, "meis": {}, "docs": {}, "cas": {}, "links": {}})
        self._apis: dict = {}

    # ------------------------------------------------------------------ helpers
    @property
    def options(self) -> dict:
        return self.inp.get("options") or {}

    def api(self, service: str):
        if service not in self._apis:
            self._apis[service] = self.client_for(service)
        return self._apis[service]

    def say(self, msg: str):
        self.cp.say(msg)

    def save(self):
        self.cp.save()

    def items_in(self):
        """(source item id, its association lists) for every item in the copied tree."""
        per = self.inp.get("items") or {}
        for iid in self.cp.rec["tree"]["order"]:
            yield iid, per.get(iid) or {}

    def tid(self, iid: str):
        return self.cp.rec["items"][iid].get("target_id")

    def item_ref(self, iid: str) -> dict:
        t = self.tid(iid)
        return ref(self.space, MFG_REL, t, self.cp.rec["tree"]["items"][iid].get("type", ""))

    def title(self, iid: str) -> str:
        return self.cp.rec["items"][iid]["title"]

    def links(self, kind: str, status: str | None = None):
        for k, l in self.st["links"].items():
            if l["kind"] == kind and (status is None or l["status"] == status):
                yield k, l

    # ------------------------------------------------------------------ plan
    async def plan(self):
        """Work out every link, look things up in the target. Writes nothing."""
        opts, links = self.options, self.st["links"]
        for iid, a in self.items_in():
            x = self.cp.rec["items"][iid]
            copied = x["action"] == "create"
            why = "" if copied else ("item reused from the target: its associations are left as they are"
                                     if x["action"] == "reuse" else "inside a reused item: not copied")
            for kind in KINDS:
                if not opts.get(kind):
                    continue
                for entry in a.get(kind) or []:
                    rid = entry if isinstance(entry, str) else (entry.get("id") or entry.get("mei"))
                    key = f"{kind}|{iid}|{rid}"
                    l = links.setdefault(key, {"kind": kind, "item": iid, "ref": rid, "status": "pending"})
                    if isinstance(entry, dict):
                        l["data"] = entry
                    if l["status"] != "done":
                        l["status"], l["note"] = ("pending", "") if copied else ("skip", why)
        # options switched off since an earlier plan
        for k, l in list(links.items()):
            if not opts.get(l["kind"]) and l["status"] != "done":
                del links[k]
        jobs = []
        if opts.get("plants"):
            jobs.append(self.plan_plants())
        if opts.get("meis"):
            jobs.append(self.plan_meis())
        if opts.get("specs"):
            self.plan_docs()
        if opts.get("changeActions"):
            self.plan_cas()
        await asyncio.gather(*jobs)
        self.save()

    async def plan_plants(self):
        names: dict[str, str] = {}
        for _, l in self.links("plants"):
            d = l.get("data") or {}
            names[norm(d.get("name") or l["ref"])] = d.get("name") or l["ref"]
        for key, name in names.items():
            p = self.st["plants"].setdefault(key, {"name": name})
            if p.get("target_id"):
                continue
            try:
                hits = await self.find_plant(name)
                if len(hits) == 1:
                    p.update(status="found", target_id=hits[0]["id"], via=hits[0].get("via"), error="")
                elif hits:
                    p.update(status="ambiguous", error=f"{len(hits)} plants named '{name}' in the target")
                else:
                    p.update(status="missing", error=f"no plant named '{name}' found in the target "
                                                      f"(searched — {getattr(self, '_last_seen', '')})")
            except Pending as e:
                p.update(status="unknown", error=str(e))
            except Exception as e:
                p.update(status="error", error=f"plant lookup failed: {e}")
        for _, l in self.links("plants"):
            if l["status"] == "pending":
                p = self.st["plants"][norm((l.get("data") or {}).get("name") or l["ref"])]
                if p.get("status") != "found":
                    l["status"], l["note"] = "skip", p.get("error") or "plant not found in the target"

    async def find_plant(self, name: str) -> list[dict]:
        """Plants in the target with exactly this name: [{id, name, via}].

        Tries the organizations resource search, then 3DSearch. Only exact (case-insensitive)
        name matches of type Plant count. A search that works but finds nothing means missing;
        if no search works at all the plant is reported as 'lookup failed' and never guessed."""
        if not PLANT_API["confirmed"]:
            raise Pending("plant lookup is switched off")
        worked, errors, seen = False, [], []
        for via, search in (("organizations list", self._plants_org_list), ("3DSearch", self._plants_3dsearch)):
            try:
                hits = await search(name)
            except Exception as e:
                errors.append(f"{via}: {str(e)[:160]}")
                continue
            worked = True
            seen.append(f"{via}: " + (", ".join(f"{h.get('name')} [{h.get('type') or '?'}]" for h in hits[:6]) or "no results"))
            exact = {}
            for h in hits:
                if norm(h.get("name")) == norm(name) and "plant" in norm(h.get("type") or "plant") and h.get("id"):
                    exact[h["id"]] = {"id": h["id"], "name": h["name"], "via": via}
            if exact:
                return list(exact.values())
        if worked:
            self._last_seen = "; ".join(seen + errors)
            return []
        raise Pending("no plant search worked in the target (" + "; ".join(errors) + ")")

    async def _plants_org_list(self, name: str) -> list[dict]:
        """GET .../organizations lists the organizations the user can see (Lighthouse answers it;
        its /search sub-route fails with HTTP 500). Read once per run."""
        if getattr(self, "_orgs", None) is None:
            api = self.api("org")
            r = await api.call("GET", "/organizations", params={"$top": 1000})
            rows = (r.get("data") if isinstance(r, dict) else None) or api.members(r) or []
            self._orgs = [{"id": m.get("id") or m.get("identifier") or m.get("physicalid"),
                           "name": (m.get("dataelements") or m).get("title") or m.get("name"),
                           "alt": m.get("name"), "type": m.get("type") or ""} for m in rows]
        out = []
        for o in self._orgs:          # a plant may carry its name in title or in name
            for label in {o["name"], o["alt"]}:
                if label and norm(label) == norm(name):
                    out.append({"id": o["id"], "name": label, "type": o["type"]})
        return out

    async def _plants_3dsearch(self, name: str) -> list[dict]:
        """3DSearch, the service behind the dashboard search box. On Lighthouse
        '[ds6w:type]:Plant AND RSK' and '[ds6w:label]:RSK' find the plant ('Org:RSK' does not)."""
        api, out, last = self.api("search"), [], None
        quoted = name if re.fullmatch(r"[\w.-]+", name) else '"' + name.replace('"', "") + '"'
        queries = [(f"[ds6w:type]:Plant AND [ds6w:label]:{quoted}", True), (f"[ds6w:type]:Plant AND {quoted}", True),
                   (f"[ds6w:label]:{quoted}", False)]
        for query, typed in queries:
            body = {"label": "mbom-copier", "locale": "en", "with_indexing_date": False, "with_synthesis": False, "with_nls": False,
                    "select_predicate": ["ds6w:label", "ds6w:type", "physicalid", "ds6w:identifier"], "select_file": [],
                    "query": query, "order_field": "relevance", "order_dir": "desc",
                    "nresults": 50, "start": "0", "source": ["3dspace"], "tenant": self.cp.rec["target"]}
            try:
                r = await api.call("POST", "/search", json=body)
            except Exception as e:
                last = e
                continue
            for res in (r.get("results") or []):
                a = {x.get("name"): x.get("value") for x in res.get("attributes") or []}
                t = a.get("ds6w:type") or ("Plant" if typed else "")      # the query already asked for plants
                out.append({"id": a.get("physicalid") or a.get("resourceid"), "name": a.get("ds6w:label"), "type": t})
            if any(norm(h["name"]) == norm(name) and "plant" in norm(h["type"]) for h in out):
                break
        if not out and last:
            raise last
        return [h for h in out if "plant" in norm(h["type"])]

    async def plan_meis(self):
        meis = self.inp.get("meis") or {}
        needed = {l["ref"] for _, l in self.links("meis") if l["status"] != "skip"}
        api = self.api("mei")

        async def one(mid: str):
            m, s = meis.get(mid) or {}, self.st["meis"].setdefault(mid, {})
            if s.get("created"):
                return
            mpn, mfr = m.get("mpn") or "", m.get("manufacturer") or ""
            if not mpn:
                s.update(action="skip", error="the source MEI has no manufacturer part number")
                return
            if not mfr and not m.get("manufacturerCompany"):
                s.update(action="skip", error="the source MEI's manufacturer could not be read")
                return
            try:
                hits = api.members(await api.call("GET", "/dssrc:ManufacturerEquivalentItems/search", params={
                    "$searchStr": mpn, "$mask": "dsmvsrc:ManufacturerEquivalentItem.Details", "$top": 50}))
            except Exception as e:
                s.update(action="error", error=f"MEI search failed: {e}")
                return
            same = [h for h in hits if norm(h.get("manufacturerPartNumber")) == norm(mpn)
                    and (not mfr or norm(h.get("manufacturer")) == norm(mfr))]
            if len(same) >= 1:
                s.update(action="reuse", target_id=same[0]["id"], target_name=same[0].get("name"), error="",
                         note="" if len(same) == 1 else f"{len(same)} matching MEIs in the target; using {same[0].get('name')}")
            else:
                s.update(action="create", target_id=None, error="", note="")
        await asyncio.gather(*(one(m) for m in needed))
        for _, l in self.links("meis"):
            s = self.st["meis"].get(l["ref"]) or {}
            if l["status"] == "pending" and s.get("action") in ("skip", "error"):
                l["status"], l["note"] = "skip", s.get("error")

    def plan_docs(self):
        docs = self.inp.get("docs") or {}
        for _, l in self.links("specs"):
            s = self.st["docs"].setdefault(l["ref"], {})
            if not docs.get(l["ref"]):
                l["status"], l["note"] = "skip", "document details were not read from the source"
            elif not s.get("target_id"):
                s.setdefault("status", "pending")

    def plan_cas(self):
        cas = self.inp.get("changeActions") or {}
        for _, l in self.links("changeActions"):
            self.st["cas"].setdefault(l["ref"], {"status": "pending"})
            if not cas.get(l["ref"]):
                l["status"], l["note"] = "skip", "change action details were not read from the source"

    # ------------------------------------------------------------------ for the UI / plan
    def files_needed(self) -> list[dict]:
        """Source files the service still needs from the widget before it can create documents."""
        docs, out = self.inp.get("docs") or {}, []
        want = {l["ref"] for _, l in self.links("specs", "pending")}
        for did in want:
            if self.st["docs"].get(did, {}).get("target_id"):
                continue
            for f in (docs.get(did) or {}).get("files") or []:
                if not (self.file_dir / safe(f["id"])).exists():
                    out.append({"doc": did, "file": f["id"], "name": f.get("name"), "size": f.get("size")})
        return out

    def counts(self) -> dict:
        c = {k: {"pending": 0, "done": 0, "skip": 0, "error": 0, "waiting": 0} for k in KINDS}
        for _, l in self.st["links"].items():
            st = l["status"] if l["status"] in ("pending", "done", "skip", "error") else "pending"
            if st == "pending" and l["kind"] == "changeActions" and not CA_API["confirmed"]:
                st = "waiting"           # planned, but nothing can be written until the spec is in
            c[l["kind"]][st] += 1
        c["new"] = {"meis": sum(1 for s in self.st["meis"].values() if s.get("action") == "create" and not s.get("created")),
                    "docs": sum(1 for d, s in self.st["docs"].items() if not s.get("target_id")
                                and any(l["ref"] == d for _, l in self.links("specs", "pending"))),
                    "cas": 0 if not CA_API["confirmed"] else
                           sum(1 for a, s in self.st["cas"].items() if not s.get("target_id")
                               and any(l["ref"] == a for _, l in self.links("changeActions", "pending")))}
        return c

    def failed(self) -> int:
        return sum(1 for _, l in self.st["links"].items() if l["status"] == "error")

    def warnings(self) -> list[str]:
        w, c = [], self.counts()
        missing = sorted({p["name"] for p in self.st["plants"].values() if p.get("status") in ("missing", "ambiguous")})
        if missing:
            w.append("Plants not in the target (their links are skipped): " + ", ".join(missing))
        failed = [p for p in self.st["plants"].values() if p.get("status") == "unknown"]
        if failed:
            w.append("Plant links skipped: the plant search did not work in the target — " + failed[0].get("error", ""))
        if c["changeActions"]["waiting"]:
            w.append("Change Actions are planned, but will only be created once the Change Action API spec is in")
        return w

    def badges(self, iid: str) -> list[dict]:
        """One entry per association of a tree row, for the table."""
        out, inp = [], self.inp
        for key, l in self.st["links"].items():
            if l["item"] != iid:
                continue
            kind, rid, d = l["kind"], l["ref"], l.get("data") or {}
            note = l.get("note") or ""
            if kind == "plants":
                p = self.st["plants"].get(norm(d.get("name") or rid), {})
                label = f"{d.get('name') or rid}" + (f" ({d.get('makeOrBuy')})" if d.get("makeOrBuy") else "")
                action = {"found": "link", "missing": "missing", "ambiguous": "missing", "unknown": "lookup-failed"}.get(p.get("status"), "check")
                if p.get("status") == "found" and not note:
                    note = f"found in the target by name ({p.get('via')})"
            elif kind == "meis":
                m, s = (inp.get("meis") or {}).get(rid, {}), self.st["meis"].get(rid, {})
                label = " · ".join(x for x in (m.get("manufacturer"), m.get("mpn") or m.get("title")) if x)
                action = s.get("action") or "check"
            elif kind == "specs":
                doc = (inp.get("docs") or {}).get(rid, {})
                files = ", ".join(f.get("name", "") for f in doc.get("files") or [])
                label = (doc.get("title") or doc.get("name") or rid) + (f" — {files}" if files else "")
                action = "create" if not self.st["docs"].get(rid, {}).get("target_id") else "link"
            else:
                ca = (inp.get("changeActions") or {}).get(rid, {})
                label = (ca.get("name") or rid) + (f" {ca.get('title')}" if ca.get("title") and ca.get("title") != ca.get("name") else "") + \
                        (f" ({str(d.get('impact')).lower()})" if d.get("impact") else "")
                action = "create" if not self.st["cas"].get(rid, {}).get("target_id") else "link"
                if not CA_API["confirmed"]:
                    action = "pending-spec"
                elif l["status"] != "skip" and not note:
                    note = ("added as a proposed change (in the source: " + str(d.get("impact") or "impact").lower() +
                            "); state, approvals and realized changes start fresh")
            out.append({"kind": kind, "label": label, "action": action, "status": l["status"],
                        "note": note, "error": l.get("error") or ""})
        order = {k: i for i, k in enumerate(KINDS)}
        return sorted(out, key=lambda b: order[b["kind"]])

    # ------------------------------------------------------------------ execute
    async def execute(self):
        opts = self.options
        if opts.get("specs"):
            await self.run_docs()
        if opts.get("plants"):
            await self.run_plants()
        if opts.get("meis"):
            await self.run_meis()
        if opts.get("changeActions"):
            await self.run_cas()
        self.save()

    def _fail(self, l: dict, msg: str):
        l["status"], l["error"] = "error", msg
        self.say(f"  FAILED  {LABEL[l['kind']]} on {self.title(l['item'])}: {msg}")
        self.save()

    def _done(self, l: dict, **kw):
        l.update(status="done", error="", **kw)
        self.save()

    # ---- specifications
    async def run_docs(self):
        docs, api = self.inp.get("docs") or {}, self.api("docs")
        by_doc: dict[str, list] = {}
        for _, l in self.links("specs"):
            if l["status"] in ("pending", "error"):
                by_doc.setdefault(l["ref"], []).append(l)
        for did, ls in by_doc.items():
            ls = [l for l in ls if self.tid(l["item"])]
            if not ls:
                continue
            s, d = self.st["docs"].setdefault(did, {}), docs[did]
            label = d.get("title") or d.get("name") or did
            if not s.get("target_id"):
                # created on the first item that has it, then attached to the others
                first = ls.pop(0)
                try:
                    s.update(target_id=await self.create_document(api, d, self.tid(first["item"])), status="created", error="")
                except Exception as e:
                    s.update(status="error", error=str(e))
                    for l in [first] + ls:
                        self._fail(l, f"document {label}: {e}")
                    continue
                self._done(first)
                self.say(f"  document {label} created on {self.title(first['item'])}")
            for l in ls:
                try:
                    await self.attach_document(api, s["target_id"], self.tid(l["item"]))
                    self._done(l)
                except Exception as e:
                    self._fail(l, f"attach {label}: {e}")

    async def create_document(self, api, d: dict, parent_tid: str) -> str:
        files = []
        for f in d.get("files") or []:
            path = self.file_dir / safe(f["id"])
            if not path.exists():
                raise RuntimeError(f"file {f.get('name')} was not received from the widget")
            files.append({"dataelements": {"title": f.get("name") or path.name,
                                           "receipt": await self.checkin(api, f.get("name") or path.name, path.read_bytes())}})
        de = {"title": d.get("title") or d.get("name"), "parentId": parent_tid, "parentRelName": "SpecificationDocument"}
        if d.get("description"):
            de["description"] = d["description"]
        body = {"data": [{"type": d.get("type") or "Document", "dataelements": de, "relateddata": {"files": files}}]}
        r = await api.call("POST", "/documents", params={"parentRelName": "SpecificationDocument"}, json=body)
        data = (r.get("data") if isinstance(r, dict) else None) or []
        if not data or not data[0].get("id"):
            raise RuntimeError("the target returned no document")
        return data[0]["id"]

    async def checkin(self, api, name: str, content: bytes) -> str:
        r = await api.call("PUT", "/files/CheckinTicket", params={"fileCount": 1})
        de = ((r.get("data") or [{}])[0].get("dataelements") or {})
        url, pname, ticket = de.get("ticketURL"), de.get("ticketparamname") or "__fcs__jobTicket", de.get("ticket")
        if not url or not ticket:
            raise RuntimeError("no check-in ticket from the target")
        fcs = self._fcs or httpx.AsyncClient(timeout=300)
        try:
            up = await fcs.post(url, data={pname: ticket}, files={"bfile": (name, content)})
            if up.status_code >= 400:
                raise RuntimeError(f"file server refused {name}: HTTP {up.status_code}")
            receipt = up.text.strip()
            if not receipt:
                raise RuntimeError(f"file server returned no receipt for {name}")
            return receipt
        finally:
            if self._fcs is None:
                await fcs.aclose()

    async def attach_document(self, api, doc_tid: str, parent_tid: str):
        await api.call("PUT", f"/{doc_tid}", params={"parentRelName": "SpecificationDocument"}, json={"data": [{
            "id": doc_tid, "relateddata": {"parents": [{"id": parent_tid, "updateAction": "CONNECT",
                                                        "dataelements": {"parentRelName": "SpecificationDocument"}}]}}]})

    # ---- plants
    async def run_plants(self):
        api = self.api("dsmfg")
        for _, l in list(self.links("plants")):
            if l["status"] not in ("pending", "error"):
                continue
            d = l.get("data") or {}
            p = self.st["plants"].get(norm(d.get("name") or l["ref"]), {})
            if not p.get("target_id"):
                continue
            attrs = {k: v for k, v in (d.get("attributes") or {}).items() if v not in (None, "")}
            if d.get("makeOrBuy"):
                attrs["makeOrBuy"] = d["makeOrBuy"]
            body = {"items": [{"organizationRef": {"identifier": p["target_id"], "source": self.space,
                                                   "relativePath": ORG_REL.format(p["target_id"])},
                               **({"attributes": attrs} if attrs else {})}]}
            try:
                r = await api.call("POST", f"/dsmfg:MfgItem/{self.tid(l['item'])}/dsmfg:MfgResponsibility", json=body)
                m = (api.members(r) or [{}])[0]
                self._done(l, target_id=m.get("id"))
                self.say(f"  plant {p['name']} linked to {self.title(l['item'])}")
            except Exception as e:
                self._fail(l, f"plant {p.get('name')}: {e}")

    # ---- MEIs
    async def run_meis(self):
        meis, mei_api, q_api = self.inp.get("meis") or {}, self.api("mei"), self.api("qual")
        for _, l in list(self.links("meis")):
            if l["status"] not in ("pending", "error"):
                continue
            mid, s = l["ref"], self.st["meis"].setdefault(l["ref"], {})
            m = meis.get(mid) or {}
            try:
                if not s.get("target_id"):
                    s["target_id"] = await self.create_mei(mei_api, m, l["item"])
                    s.update(created=True, error="")
                    self.save()
                    self.say(f"  MEI {m.get('manufacturer')} {m.get('mpn')} created")
                q = (l.get("data") or {}).get("qualification") or {}
                body = {"data": [{
                    "type": q.get("apiType") or "manufacturingEquivalentQualification",
                    "preferred": yes_no(q.get("preferred")), "approved": yes_no(q.get("approved") or "Yes"),
                    **{k: q[k] for k in ("description", "comments", "restriction") if q.get(k)},
                    "target": ref(self.space, MEI_REL, s["target_id"], "Manufacturer Equivalent Item"),
                    "context": [self.item_ref(l["item"])]}]}
                r = await q_api.call("POST", "/qualifications", json=body)
                data = (r.get("data") if isinstance(r, dict) else None) or [{}]
                self._done(l, target_id=data[0].get("id"))
                self.say(f"  MEI {m.get('mpn')} qualified on {self.title(l['item'])}")
            except Exception as e:
                s["error"] = str(e)
                self._fail(l, f"MEI {m.get('manufacturer') or ''} {m.get('mpn') or ''}: {e}")

    async def create_mei(self, api, m: dict, iid: str) -> str:
        if not m.get("mpn"):
            raise RuntimeError("no manufacturer part number")
        rec = {"engItem": {k: v for k, v in self.item_ref(iid).items() if k != "id"},
               "manufacturerPartNumber": m["mpn"]}
        if m.get("manufacturerCompany"):
            rec["manufacturerCompany"] = m["manufacturerCompany"]
        else:
            rec["manufacturer"] = m.get("manufacturer") or ""
        for k in ("partSource", "partSourceURL"):
            if m.get(k):
                rec[k] = m[k]
        r = await api.call("POST", "/dssrc:ManufacturerEquivalentItems", json=[rec])
        mm = (api.members(r) or [{}])[0]
        new = mm.get("id") or mm.get("identifier") or str(mm.get("relativePath") or "").rstrip("/").split("/")[-1]
        if not new:
            raise RuntimeError("the target returned no MEI")
        return new

    # ---- change actions
    async def run_cas(self):
        """One new CA per source CA; the copied items it impacted become its proposed changes."""
        if not CA_API["confirmed"]:
            for _, l in self.links("changeActions", "pending"):
                l["note"] = "waiting for the Change Action API spec; not created yet"
            self.save()
            return
        cas, api = self.inp.get("changeActions") or {}, self.api("ca")
        by_ca: dict[str, list] = {}
        for _, l in self.links("changeActions"):
            if l["status"] in ("pending", "error") and self.tid(l["item"]):
                by_ca.setdefault(l["ref"], []).append(l)
        for cid, ls in by_ca.items():
            src, s = cas.get(cid) or {}, self.st["cas"].setdefault(cid, {})
            label = src.get("name") or cid
            try:
                if not s.get("target_id"):
                    body = {"title": src.get("title") or src.get("name") or "Copied change action",
                            "description": src.get("description") or
                            f"Copy of {src.get('name') or cid} from {self.cp.source}" + (f": {src['title']}" if src.get("title") else ""),
                            "severity": src.get("severity") if src.get("severity") in ("Low", "Medium", "High") else "Low"}
                    r = await api.call("POST", "/changeaction", json=body)
                    if not r.get("id"):
                        raise RuntimeError("the target returned no change action")
                    s.update(target_id=r["id"], target_name=r.get("name"), cestamp=r.get("cestamp"), status="created", error="")
                    self.save()
                    self.say(f"  change action {r.get('name')} created (copy of {label})")
            except Exception as e:
                s.update(status="error", error=str(e))
                for l in ls:
                    self._fail(l, f"change action {label}: {e}")
                continue
            for i in range(0, len(ls), CA_API["batch"]):
                batch = ls[i:i + CA_API["batch"]]
                try:
                    if not s.get("cestamp"):
                        s["cestamp"] = (await api.call("GET", f"/changeaction/{s['target_id']}")).get("cestamp")
                    body = {"cestamp": s["cestamp"], "add": [{"proposedChanges": [{
                        "where": {k: v for k, v in self.item_ref(l["item"]).items() if k != "id"},
                        "target": CA_API["target"], "whats": [{"what": CA_API["what"]}]} for l in batch]}]}
                    try:
                        r = await api.call("PATCH", f"/changeaction/{s['target_id']}", json=body)
                    except Exception:
                        # stale cestamp (someone else touched the CA): read it again once
                        s["cestamp"] = (await api.call("GET", f"/changeaction/{s['target_id']}")).get("cestamp")
                        body["cestamp"] = s["cestamp"]
                        r = await api.call("PATCH", f"/changeaction/{s['target_id']}", json=body)
                    s["cestamp"] = r.get("cestamp") or None
                    for l in batch:
                        self._done(l, target_id=s["target_id"])
                    self.say(f"  {len(batch)} item(s) added to {s.get('target_name') or s['target_id']}")
                except Exception as e:
                    s["cestamp"] = None
                    for l in batch:
                        self._fail(l, f"add to change action {s.get('target_name') or label}: {e}")

    async def ca_proposed(self, ca_tid: str) -> set:
        """Item ids that are proposed changes of a target CA (read once per verification)."""
        if ca_tid not in self._ca_pc:
            async def read():
                r = await self.api("ca").call("GET", f"/changeaction/{ca_tid}", params={"$fields": "proposedChanges"})
                return {(pc.get("where") or {}).get("identifier") for pc in r.get("proposedChanges") or []}
            self._ca_pc[ca_tid] = asyncio.ensure_future(read())
        return await self._ca_pc[ca_tid]

    # ------------------------------------------------------------------ verify
    async def verify(self) -> list[str]:
        problems, items = [], {}
        for _, l in self.st["links"].items():
            if l["status"] == "done":
                items.setdefault(l["item"], []).append(l)
        dsmfg, docs, qual = None, None, None

        async def one(iid: str, ls: list):
            nonlocal dsmfg, docs, qual
            tid, kinds = self.tid(iid), {l["kind"] for l in ls}
            try:
                if "specs" in kinds:
                    docs = docs or self.api("docs")
                    r = await docs.call("GET", f"/parentId/{tid}", params={"parentRelName": "SpecificationDocument"})
                    have = {d.get("id") for d in (r.get("data") or [])}
                    for l in ls:
                        if l["kind"] == "specs" and self.st["docs"][l["ref"]]["target_id"] not in have:
                            problems.append(f"{self.title(iid)}: specification {l['ref']} is not attached in the target")
                if "plants" in kinds:
                    dsmfg = dsmfg or self.api("dsmfg")
                    r = await dsmfg.call("GET", f"/dsmfg:MfgItem/{tid}/dsmfg:MfgResponsibility")
                    have = {(m.get("organizationRef") or {}).get("identifier") for m in dsmfg.members(r)}
                    for l in ls:
                        if l["kind"] == "plants":
                            p = self.st["plants"][norm((l.get("data") or {}).get("name") or l["ref"])]
                            if p["target_id"] not in have:
                                problems.append(f"{self.title(iid)}: plant {p['name']} is not linked in the target")
                if "changeActions" in kinds:
                    for l in ls:
                        if l["kind"] != "changeActions":
                            continue
                        c = self.st["cas"][l["ref"]]
                        if tid not in await self.ca_proposed(c["target_id"]):
                            problems.append(f"{self.title(iid)}: not among the proposed changes of {c.get('target_name')} in the target")
                if "meis" in kinds:
                    qual = qual or self.api("qual")
                    r = await qual.call("POST", "/qualifications/contextLocate",
                                        params={"type": "manufacturingEquivalentQualification", "$include": "target,contexts"},
                                        json={"data": [self.item_ref(iid)]})
                    have = {(q.get("target") or {}).get("id") or (q.get("target") or {}).get("identifier")
                            for q in ((r.get("result", r) or {}).get("data") or [])}
                    for l in ls:
                        if l["kind"] == "meis" and self.st["meis"][l["ref"]]["target_id"] not in have:
                            problems.append(f"{self.title(iid)}: MEI qualification for {l['ref']} not found in the target")
            except Exception as e:
                problems.append(f"{self.title(iid)}: could not read associations back ({e})")
        self._ca_pc = {}
        await asyncio.gather(*(one(i, ls) for i, ls in items.items()))
        self.cp.rec.setdefault("verification", {})["associations"] = problems
        self.save()
        return problems


def safe(name: str) -> str:
    return re.sub(r"[^\w.-]", "_", str(name))


def store_file(file_dir: Path, file_id: str, b64: str) -> int:
    file_dir.mkdir(parents=True, exist_ok=True)
    data = base64.b64decode(b64)
    (file_dir / safe(file_id)).write_bytes(data)
    return len(data)
