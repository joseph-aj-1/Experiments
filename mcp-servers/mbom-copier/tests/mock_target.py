"""In-memory target tenant with the web services the association copy uses:
dsmfg (items, instances, Manufacturing Responsibility), Sourcing (MEIs, qualifications),
Documents (check-in tickets, create, attach, where-used) and a file server (FCS).
Shapes follow the OpenAPI specs in tdx-mcp-server/specs."""
from __future__ import annotations

import json
import re
from email.parser import BytesParser

import httpx

from test_copy import Tenant

FCS = "https://fcs.test/fcs/servlet/fcs/checkin"
BASES = {"dsmfg": "/api/dsmfg/v1", "mei": "/api/dssrc-manufacturerEquivalentItems/v1",
         "qual": "/api/dssrc-qualifications/v1", "docs": "/api/documents/v1"}


class FullTenant(Tenant):
    def __init__(self, tid: str, **kw):
        super().__init__(tid, **kw)
        self.plants: dict[str, dict] = {}
        self.resp: dict[str, list] = {}
        self.meis: dict[str, dict] = {}
        self.quals: list[dict] = []
        self.docs: dict[str, dict] = {}
        self.tickets: set[str] = set()
        self.receipts: dict[str, tuple] = {}
        self.fail_service: str | None = None       # make one web service refuse writes

    def add_plant(self, name):
        pid = next(self.ids)
        self.plants[pid] = {"id": pid, "name": name, "title": name, "type": "Plant"}
        return pid

    def add_mei(self, mpn, manufacturer, **extra):
        mid = next(self.ids)
        self.meis[mid] = {"id": mid, "name": f"prd-{self.tid}-{next(self.seq):08d}", "title": mpn, "type": "Physical Product",
                          "manufacturerPartNumber": mpn, "manufacturer": manufacturer, "revision": "A", "state": "IN_WORK", **extra}
        return mid

    # ------------------------------------------------------------------ routing
    def handler(self, req: httpx.Request) -> httpx.Response:
        if req.url.host == "fcs.test":
            return self.fcs(req)
        p = req.url.path
        for svc, base in BASES.items():
            if base in p:
                if req.method != "GET" and self.fail_service == svc:
                    return httpx.Response(503, text="Service unavailable")
                if svc == "dsmfg":
                    sub = p.split(base, 1)[1]
                    m = re.fullmatch(r"/dsmfg:MfgItem/(\w+)/dsmfg:MfgResponsibility", sub)
                    if m:
                        return self.responsibility(req, m.group(1))
                    return super().handler(req)
                return getattr(self, "h_" + svc)(req, p.split(base, 1)[1], json.loads(req.content) if req.content and
                                          req.headers.get("content-type", "").startswith("application/json") else None)
        return httpx.Response(404, json={"message": f"no service for {p}"})

    def responsibility(self, req, iid):
        self.calls.append((req.method, f"responsibility {iid}"))
        if iid not in self.items:
            return httpx.Response(404, json={"message": "not found"})
        if req.method == "GET":
            return self.ok(self.resp.get(iid, []))
        body = json.loads(req.content)
        if len(body["items"]) != 1:
            return httpx.Response(400, json={"message": "Only 1 item could be created per call on cloud"})
        org = body["items"][0]["organizationRef"]["identifier"]
        if org not in self.plants:
            return httpx.Response(400, json={"message": f"organization {org} not found"})
        link = {"id": next(self.ids), "type": "DELMfgResponsibilityCnx",
                "organizationRef": {"identifier": org, "type": "Plant", "relativePath": f"/resources/v1/modeler/organizations/{org}"},
                **(body["items"][0].get("attributes") or {})}
        self.resp.setdefault(iid, []).append(link)
        return self.ok([link])

    def h_mei(self, req, path, body):
        self.calls.append((req.method, f"mei {path}"))
        if req.method == "GET" and path == "/dssrc:ManufacturerEquivalentItems/search":
            q = req.url.params.get("$searchStr", "").lower()
            return self.ok([m for m in self.meis.values() if q in m["manufacturerPartNumber"].lower() or q in m["title"].lower()])
        if req.method == "POST" and path == "/dssrc:ManufacturerEquivalentItems":
            if not isinstance(body, list) or len(body) != 1:
                return httpx.Response(400, json={"message": "array of one MEI expected"})
            r = body[0]
            if not r.get("manufacturerPartNumber") or not (r.get("manufacturer") or r.get("manufacturerCompany")):
                return httpx.Response(400, json={"message": "manufacturerPartNumber and manufacturer are required"})
            if (r.get("engItem") or {}).get("identifier") not in self.items:
                return httpx.Response(400, json={"message": "engItem not found"})
            mfr = r.get("manufacturer") or (r.get("manufacturerCompany") or {}).get("name") or "?"
            mid = self.add_mei(r["manufacturerPartNumber"], mfr, partSource=r.get("partSource", ""))
            return self.ok([{**self.meis[mid], "relativePath": f"/resources/v1/modeler/dssrc/dssrc:ManufacturerEquivalentItems/{mid}"}])
        return httpx.Response(404, json={"message": f"no route {path}"})

    def h_qual(self, req, path, body):
        self.calls.append((req.method, f"qual {path}"))
        if req.method == "POST" and path == "/qualifications":
            d = body["data"][0]
            if d.get("type") not in ("manufacturingEquivalentQualification", "equivalentQualification", "generalQualification"):
                return httpx.Response(400, json={"message": f"bad type {d.get('type')}"})
            if d.get("preferred") not in ("Yes", "No") or d.get("approved") not in ("Yes", "No"):
                return httpx.Response(400, json={"message": "preferred/approved must be Yes or No"})
            tgt = (d.get("target") or {}).get("identifier")
            ctx = [(c.get("identifier") or c.get("id")) for c in d.get("context") or []]
            if tgt not in self.meis or not ctx or any(c not in self.items for c in ctx):
                return httpx.Response(400, json={"message": "target MEI or context item not found"})
            q = {"id": next(self.ids), "name": f"MQ-{next(self.seq):06d}", "type": "SRC Manufacturing Equivalent Qualification",
                 "preferred": "TRUE" if d["preferred"] == "Yes" else "FALSE", "approved": d["approved"],
                 "target": {"id": tgt, "identifier": tgt}, "contexts": [{"id": c, "identifier": c} for c in ctx]}
            self.quals.append(q)
            return httpx.Response(200, json={"success": True, "data": [q]})
        if req.method == "POST" and path == "/qualifications/contextLocate":
            ids = {(x.get("identifier") or x.get("id")) for x in body["data"]}
            out = [q for q in self.quals if any(c["id"] in ids for c in q["contexts"])]
            return httpx.Response(200, json={"result": {"success": True, "data": out}})
        return httpx.Response(404, json={"message": f"no route {path}"})

    def h_docs(self, req, path, body):
        self.calls.append((req.method, f"docs {path}"))
        if req.method == "PUT" and path == "/files/CheckinTicket":
            t = f"T{next(self.seq)}"
            self.tickets.add(t)
            return httpx.Response(200, json={"success": True, "data": [{"dataelements": {
                "ticketURL": FCS, "ticketparamname": "__fcs__jobTicket", "ticket": t}}]})
        if req.method == "POST" and path == "/documents":
            d = body["data"][0]
            de = d.get("dataelements") or {}
            parent = de.get("parentId")
            if parent and parent not in self.items:
                return httpx.Response(400, json={"message": "parent not found"})
            files = []
            for f in (d.get("relateddata") or {}).get("files") or []:
                rc = (f.get("dataelements") or {}).get("receipt")
                if rc not in self.receipts:
                    return httpx.Response(400, json={"message": "invalid receipt"})
                files.append({"name": f["dataelements"].get("title"), "bytes": self.receipts.pop(rc)[1]})
            did = next(self.ids)
            self.docs[did] = {"id": did, "title": de.get("title"), "description": de.get("description"), "files": files,
                              "parents": {parent} if parent and (req.url.params.get("parentRelName") or de.get("parentRelName")) == "SpecificationDocument" else set()}
            return httpx.Response(200, json={"success": True, "data": [{"id": did, "type": "Document", "dataelements": {"title": de.get("title")}}]})
        m = re.fullmatch(r"/parentId/(\w+)", path)
        if req.method == "GET" and m:
            rel = req.url.params.get("parentRelName")
            out = [{"id": d["id"], "dataelements": {"title": d["title"]}} for d in self.docs.values()
                   if rel == "SpecificationDocument" and m.group(1) in d["parents"]]
            return httpx.Response(200, json={"success": True, "data": out})
        m = re.fullmatch(r"/(\w+)", path)
        if req.method == "PUT" and m and m.group(1) in self.docs:
            for p in (body["data"][0].get("relateddata") or {}).get("parents") or []:
                if p.get("updateAction") != "CONNECT" or p.get("id") not in self.items:
                    return httpx.Response(400, json={"message": "bad parent"})
                self.docs[m.group(1)]["parents"].add(p["id"])
            return httpx.Response(200, json={"success": True, "data": [{"id": m.group(1)}]})
        return httpx.Response(404, json={"message": f"no route {req.method} {path}"})

    def fcs(self, req):
        ctype = req.headers.get("content-type", "")
        msg = BytesParser().parsebytes(b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + req.content)
        fields, file = {}, None
        for part in msg.get_payload():
            name = part.get_param("name", header="content-disposition")
            if part.get_filename():
                file = (part.get_filename(), part.get_payload(decode=True))
            else:
                fields[name] = part.get_payload(decode=True).decode()
        t = fields.get("__fcs__jobTicket")
        if t not in self.tickets or not file:
            return httpx.Response(403, text="bad ticket")
        self.tickets.discard(t)
        rc = f"RECEIPT-{t}"
        self.receipts[rc] = file
        return httpx.Response(200, text=rc + "\n")

    # ------------------------------------------------------------------ clients
    def client(self, service: str = "dsmfg"):
        c = httpx.AsyncClient(base_url=f"https://{self.tid.lower()}-us1-apigateway.test{BASES[service]}",
                              transport=httpx.MockTransport(self.handler), headers={"SecurityContext": "ctx::Role.Org.Space"})
        c.tenant_id = self.tid
        return c

    def fcs_client(self):
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    @property
    def space(self):
        return f"https://{self.tid.lower()}-us1-space.test/enovia"
