"""In-memory stand-in for the 3DEXPERIENCE dsmfg / dspfl web services, shaped on
real responses from tenant OI000629352 (October 2026). Used by test_builder.py."""
from __future__ import annotations

import itertools
import json
import re

import httpx


class MockTenant:
    def __init__(self, fail_after: int | None = None):
        self.ids = (f"{n:032X}" for n in itertools.count(0xE313E8101C0D28006AD2000000000001))
        self.items, self.instances, self.models, self.variants, self.values = {}, {}, {}, {}, {}
        self.attached, self.criteria, self.effectivity = {}, {}, {}
        self.calls, self.fail_after = 0, fail_after
        self.counters = itertools.count(1)

    def nid(self):
        return next(self.ids)

    # ----------------------------------------------------------------- routing
    def handler(self, req: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.fail_after is not None and req.method != "GET" and self.calls > self.fail_after:
            return httpx.Response(503, text="Service unavailable")
        path = req.url.path.split("/v1", 1)[1]
        body = json.loads(req.content) if req.content else None
        m = req.method
        try:
            # ---- portfolio
            if m == "GET" and path == "/dspfl:ModelVersion/search":
                q = req.url.params.get("$searchStr", "")
                return self.ok([x for x in self.models.values() if q.lower() in x["title"].lower()])
            if m == "POST" and path == "/dspfl:ModelVersion":
                it = body["items"][0]
                for k in ("type", "versionName"):
                    if not it.get(k):
                        return httpx.Response(400, json={"status": 400, "message": f"No value for attributes : {k}."})
                n = next(self.counters)
                model = {"id": self.nid(), "name": f"MV-TEST-{n:08d}", "type": "Model", "title": it["attributes"]["title"]}
                mv = {"id": self.nid(), "name": model["name"], "type": "Hardware Product", "title": model["title"],
                      "revision": it["versionName"], "model": {"totalItems": 1, "member": [model]}}
                self.models[mv["id"]] = mv
                return self.ok([mv])
            if m == "POST" and path == "/dspfl:Variant":
                it = body["items"][0]
                v = {"id": self.nid(), "name": f"VAR-TEST-{next(self.counters):08d}", "title": it["attributes"]["title"], "type": "Variant"}
                self.variants[v["id"]] = v
                return self.ok([v])
            mm = re.fullmatch(r"/dspfl:Variant/(\w+)/dspfl:VariantValue", path)
            if m == "POST" and mm:
                out = []
                for it in body["items"]:
                    vv = {"id": self.nid(), "name": f"VV-TEST-{next(self.counters):08d}", "title": it["attributes"]["title"],
                          "variant": mm.group(1)}
                    self.values[vv["id"]] = vv
                    out.append(vv)
                return self.ok(out)
            if m == "POST" and re.fullmatch(r"/dspfl:ModelVersion/\w+/dspfl:VariantInstance", path):
                return self.ok([{"id": self.nid(), "constraint": "Must"}])
            # ---- items
            if m == "POST" and path == "/dsmfg:MfgItem":
                if not isinstance(body, dict):
                    return httpx.Response(400, json={"status": 400, "message": "Payload is not valid."})
                it = body["items"][0]
                x = {"id": self.nid(), "name": f"item-{next(self.counters)}", "type": it["type"],
                     "title": it["attributes"]["title"], "state": "IN_WORK"}
                self.items[x["id"]] = x
                return self.ok([x])
            mm = re.fullmatch(r"/dsmfg:MfgItem/(\w+)", path)
            if m == "GET" and mm:
                if mm.group(1) not in self.items:
                    return httpx.Response(404, json={"status": 404, "message": "URI not Found."})
                return self.ok([self.items[mm.group(1)]])
            mm = re.fullmatch(r"/dsmfg:MfgItem/(\w+)/dsmfg:MfgItemInstance", path)
            if mm and m == "POST":
                ref = body["instances"][0]["referencedObject"]["identifier"]
                i = {"id": self.nid(), "name": self.items[ref]["title"] + ".0", "reference": ref, "parent": mm.group(1)}
                self.instances[i["id"]] = i
                return self.ok([i])
            if mm and m == "GET":
                return self.ok([i for i in self.instances.values() if i["parent"] == mm.group(1)])
            mm = re.fullmatch(r"/dsmfg:MfgItem/(\w+)/dscfg:Configured/attach", path)
            if mm and m == "POST":
                self.attached.setdefault(mm.group(1), []).append(body[0]["identifier"])
                return httpx.Response(200, json={"result": {"resources": body}})
            mm = re.fullmatch(r"/dsmfg:MfgItem/(\w+)/dscfg:Configured", path)
            if mm and m == "PATCH":
                if not isinstance(body.get("enabledCriteria"), list):
                    return httpx.Response(400, json={"status": 400, "message": "Criteria list is not a JsonArray."})
                self.criteria[mm.group(1)] = body["enabledCriteria"]
                return self.ok([{"enabledCriteria": ",".join(body["enabledCriteria"])}])
            mm = re.fullmatch(r"/dsmfg:MfgItem/(\w+)/dsmfg:MfgItemInstance/(\w+)/dscfg:Filterable/set/variant", path)
            if mm and m == "POST":
                pid, iid = mm.groups()
                if "Variant" not in self.criteria.get(pid, []):
                    return httpx.Response(200, json={"errorCode": 120, "message": "The criteria is not enabled on the parent reference.",
                                                     "errorDetails": f"The reference : {pid} does not have a criteria enabled"})
                self.effectivity[iid] = self.render(body["variantContent"])
                return httpx.Response(200, json={"updated": {"id": iid}})
            mm = re.fullmatch(r"/dsmfg:MfgItem/(\w+)/dsmfg:MfgItemInstance/(\w+)/dscfg:Filterable", path)
            if mm and m == "GET":
                return self.ok([{"effectivityContent": {"Effectivity_Variant": self.effectivity.get(mm.group(2), ""),
                                                        "Effectivity_Projected_Evolution": "", "Effectivity_Current_Evolution": ""}}])
        except Exception as e:  # noqa: BLE001
            return httpx.Response(500, text=f"mock error {e}")
        return httpx.Response(404, text=f"mock: no route {m} {path}")

    def render(self, xml: str) -> str:
        """Turn the XML back into what 3DEXPERIENCE reports, e.g. 'R648 Housing: Wireless Housing{1143,1144}'."""
        model_name = re.search(r'HolderName="([^"]+)"', xml).group(1)
        names = re.findall(r'<Feature Type="ConfigFeature" Name="([^"]+)"/>', xml)
        variant_name = re.search(r'<Feature Type="ConfigFeature" Name="([^"]+)">', xml).group(1)
        model = next(x for x in self.models.values() if x["name"] == model_name)
        var = next(x for x in self.variants.values() if x["name"] == variant_name)
        titles = [next(v["title"] for v in self.values.values() if v["name"] == n) for n in names]
        return f"{model['title']}: {var['title']}{{{','.join(titles)}}}"

    @staticmethod
    def ok(member):
        return httpx.Response(200, json={"totalItems": len(member), "member": member})

    def clients(self):
        t = httpx.MockTransport(self.handler)
        return (httpx.AsyncClient(base_url="https://gw.example/api/dsmfg/v1", transport=t),
                httpx.AsyncClient(base_url="https://gw.example/api/dspfl/v1", transport=t))
