"""Builds a configured MBOM in 3DEXPERIENCE from a checked template Plan.

Order (each step is recorded in the run file as soon as it succeeds, so a
failed run can be resumed without creating anything twice):
  1. Portfolio: model version, variant, variant values, allocation
  2. Manufacturing Items (New lines) / check Existing ones
  3. Instances (quantity N -> N instances)
  4. Configuration: attach the model from the attach-to item down to the
     configured item; enable the Variant criterion on the configured item
  5. Variant effectivity on the configured item's variant-specific children
  6. Validation: read every child back and compare with the template
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import quoteattr

import httpx

from .template import Plan

log = logging.getLogger("cmb")
ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
MFG_PATH = "/resources/v1/modeler/dsmfg/dsmfg:MfgItem/{}"
MODEL_PATH = "/resources/v1/modeler/dspfl/dspfl:Model/{}"


class BuildError(RuntimeError):
    pass


def file_sha(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _clients():
    """Authenticated clients for dsmfg and dspfl, using the vendored tdx-mcp-server code."""
    from app.client_factory import build_client  # type: ignore
    from app.config import CREDENTIALS, ServiceEntry  # type: ignore

    def make(svc: str):
        spec = {"servers": [{"url": "{APIGateway}/api/" + svc + "/v1",
                             "variables": {"APIGateway": {"default": "https://my3DEXPERIENCE-APIGateway"}}}]}
        return build_client(spec, ServiceEntry(name=svc, file="", server_preference="APIGateway"), CREDENTIALS)
    return make("dsmfg"), make("dspfl")


def effectivity_xml(model_name: str, variant_name: str, value_names: list[str]) -> str:
    def feat(v: str) -> str:
        return (f'<Feature Type="ConfigFeature" Name={quoteattr(variant_name)}>'
                f'<Feature Type="ConfigFeature" Name={quoteattr(v)}/></Feature>')
    inner = feat(value_names[0]) if len(value_names) == 1 else "<OR>" + "".join(feat(v) for v in value_names) + "</OR>"
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<CfgEffectivityExpression xs:schemaLocation="urn:com:dassault_systemes:config CfgEffectivityExpression.xsd" '
            'xmlns:xs="http://www.w3.org/2001/XMLSchema-instance" xmlns="urn:com:dassault_systemes:config">'
            f'<Expression><Context HolderType="Model" HolderName={quoteattr(model_name)}>{inner}</Context></Expression>'
            '</CfgEffectivityExpression>')


class Builder:
    def __init__(self, plan: Plan, record_path: Path | None = None, mfg=None, pfl=None):
        self.plan = plan
        self.mfg, self.pfl = (mfg, pfl) if mfg is not None else _clients()
        RUNS.mkdir(exist_ok=True)
        if record_path and Path(record_path).exists():
            self.record_path = Path(record_path)
            self.rec = json.loads(self.record_path.read_text())
            self.rec.setdefault("log", []).append(f"{self._now()} resumed")
        else:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            safe = "".join(c if c.isalnum() else "_" for c in plan.model_title)[:40]
            self.record_path = RUNS / f"{stamp}_{safe}.json"
            n = 2
            while self.record_path.exists():
                self.record_path = RUNS / f"{stamp}_{safe}-{n}.json"
                n += 1
            self.rec = {"template": plan.file, "template_sha256": file_sha(plan.file),
                        "model_title": plan.model_title, "started": self._now(),
                        "status": "started", "portfolio": {}, "items": {}, "instances": {},
                        "attached": [], "criteria": False, "effectivity": {}, "log": []}
        self._save()

    # ------------------------------------------------------------------ utils
    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _save(self) -> None:
        self.record_path.write_text(json.dumps(self.rec, indent=1))

    def _log(self, msg: str) -> None:
        log.info(msg)
        self.rec["log"].append(f"{self._now()} {msg}")
        self._save()

    async def _call(self, client: httpx.AsyncClient, method: str, path: str, **kw) -> dict:
        for attempt in range(3):
            r = await client.request(method, path, **kw)
            if r.status_code in (429, 502, 503, 504) and attempt < 2:
                await asyncio.sleep(2 * (attempt + 1))
                continue
            if r.status_code >= 400:
                raise BuildError(f"{method} {path} -> HTTP {r.status_code}: {r.text[:500]}")
            data = r.json() if r.content else {}
            if isinstance(data, dict) and data.get("errorCode"):
                raise BuildError(f"{method} {path} -> {data.get('message') or data.get('errorMessage')}: "
                                 f"{data.get('errorDetails', '')}")
            return data
        raise BuildError(f"{method} {path} kept failing")

    # ------------------------------------------------------------- pre-checks
    async def model_title_exists(self) -> list[dict]:
        data = await self._call(self.pfl, "GET", "/dspfl:ModelVersion/search",
                                params={"$searchStr": self.plan.model_title, "$top": 50})
        return [m for m in data.get("member", []) if m.get("title") == self.plan.model_title]

    async def check_existing_items(self) -> list[str]:
        problems = []
        for ln in self.plan.lines:
            if ln.source == "Existing":
                try:
                    d = await self._call(self.mfg, "GET", f"/dsmfg:MfgItem/{ln.existing_id}")
                    got = (d.get("member") or [{}])[0].get("title")
                    if got and got != ln.title:
                        problems.append(f"row {ln.row}: Existing ID is '{got}', the sheet says '{ln.title}'")
                except BuildError as e:
                    problems.append(f"row {ln.row}: Existing ID {ln.existing_id} not found ({e})")
        return problems

    # ------------------------------------------------------------------ steps
    async def portfolio(self) -> None:
        p, pf = self.plan, self.rec["portfolio"]
        if "model_version_id" not in pf:
            d = await self._call(self.pfl, "POST", "/dspfl:ModelVersion", json={"items": [{
                "type": "Hardware Product", "versionName": p.model_revision,
                "attributes": {"title": p.model_title, "description": f"Built by Configured MBOM Builder from {Path(p.file).name}"}}]})
            mv = d["member"][0]
            model = mv["model"]["member"][0]
            pf.update(model_version_id=mv["id"], model_id=model["id"], model_name=model["name"])
            self._log(f"model version '{p.model_title}' created ({model['name']})")
        if "variant_id" not in pf:
            d = await self._call(self.pfl, "POST", "/dspfl:Variant", json={"items": [{
                "type": "Variant", "versionName": "A", "attributes": {"title": p.variant}}]})
            v = d["member"][0]
            pf.update(variant_id=v["id"], variant_name=v["name"])
            self._log(f"variant '{p.variant}' created ({v['name']})")
        if "values" not in pf:
            d = await self._call(self.pfl, "POST", f"/dspfl:Variant/{pf['variant_id']}/dspfl:VariantValue", json={"items": [
                {"type": "Variant Value", "versionName": "A",
                 "attributes": {"title": v["name"], "description": " ".join(x for x in (v["part_number"], v["description"]) if x),
                                "sequenceNumber": i + 1}} for i, v in enumerate(p.values)]})
            pf["values"] = {m["title"]: {"id": m["id"], "name": m["name"]} for m in d["member"]}
            self._log(f"{len(pf['values'])} variant values created")
        if not pf.get("allocated"):
            await self._call(self.pfl, "POST", f"/dspfl:ModelVersion/{pf['model_version_id']}/dspfl:VariantInstance",
                             json={"items": [{"constraint": "Must", "sequenceNumber": 1, "variant": {"id": pf["variant_id"]},
                                              "value": [{"id": pf["values"][v["name"]]["id"]} for v in p.values]}]})
            pf["allocated"] = True
            self._log("variant allocated to the model version")
        self._save()

    async def items(self) -> None:
        for ln in self.plan.lines:
            key = str(ln.row)
            if key in self.rec["items"]:
                continue
            if ln.source == "Existing":
                self.rec["items"][key] = {"title": ln.title, "id": ln.existing_id, "existing": True}
            else:
                desc = ln.description + (f" ({ln.qty_note})" if ln.qty_note else "")
                d = await self._call(self.mfg, "POST", "/dsmfg:MfgItem", json={"items": [{
                    "type": ln.type, "attributes": {"title": ln.title, "description": desc}}]})
                m = d["member"][0]
                self.rec["items"][key] = {"title": ln.title, "id": m["id"], "name": m["name"]}
            self._save()
        self._log(f"{len(self.rec['items'])} items ready")

    async def instances(self) -> None:
        lines = self.plan.lines
        for ln in lines:
            if ln.parent is None:
                continue
            key = str(ln.row)
            done = self.rec["instances"].setdefault(key, [])
            pid = self.rec["items"][str(lines[ln.parent].row)]["id"]
            cid = self.rec["items"][key]["id"]
            while len(done) < ln.qty:
                d = await self._call(self.mfg, "POST", f"/dsmfg:MfgItem/{pid}/dsmfg:MfgItemInstance", json={"instances": [{
                    "referencedObject": {"identifier": cid, "relativePath": MFG_PATH.format(cid)}}]})
                done.append(d["member"][0]["id"])
                self._save()
        self._log(f"{sum(len(v) for v in self.rec['instances'].values())} instances ready")

    async def configuration(self) -> None:
        pf = self.rec["portfolio"]
        for i in self.plan.path_down():
            key = str(self.plan.lines[i].row)
            if key in self.rec["attached"]:
                continue
            iid = self.rec["items"][key]["id"]
            await self._call(self.mfg, "POST", f"/dsmfg:MfgItem/{iid}/dscfg:Configured/attach", json=[{
                "identifier": pf["model_id"], "type": "Model", "source": "3DSpace",
                "relativePath": MODEL_PATH.format(pf["model_id"])}])
            self.rec["attached"].append(key)
            self._save()
        if not self.rec["criteria"]:
            cfg = self.plan.lines[self.plan.index_of(self.plan.configured_item)]
            await self._call(self.mfg, "PATCH", f"/dsmfg:MfgItem/{self.rec['items'][str(cfg.row)]['id']}/dscfg:Configured",
                             json={"enabledCriteria": ["Variant"]})
            self.rec["criteria"] = True
        self._log(f"model attached to {len(self.rec['attached'])} items; Variant criterion enabled")

    async def effectivity(self) -> None:
        pf = self.rec["portfolio"]
        ci = self.plan.index_of(self.plan.configured_item)
        pid = self.rec["items"][str(self.plan.lines[ci].row)]["id"]
        n = 0
        for i in self.plan.children(ci):
            ln = self.plan.lines[i]
            if ln.effectivity in ("", "ALL"):
                continue
            names = [pf["values"][v]["name"] for v in ln.values]
            xml = effectivity_xml(pf["model_name"], pf["variant_name"], names)
            for inst in self.rec["instances"][str(ln.row)]:
                if inst in self.rec["effectivity"]:
                    continue
                await self._call(self.mfg, "POST",
                                 f"/dsmfg:MfgItem/{pid}/dsmfg:MfgItemInstance/{inst}/dscfg:Filterable/set/variant",
                                 json={"variantContent": xml})
                self.rec["effectivity"][inst] = ln.effectivity
                self._save()
                n += 1
        self._log(f"variant effectivity set on {len(self.rec['effectivity'])} instances ({n} this run)")

    async def validate(self) -> dict:
        """Read the configured item's children back and compare with the template."""
        plan, rec = self.plan, self.rec
        ci = plan.index_of(plan.configured_item)
        pid = rec["items"][str(plan.lines[ci].row)]["id"]
        data = await self._call(self.mfg, "GET", f"/dsmfg:MfgItem/{pid}/dsmfg:MfgItemInstance")
        live = {m["id"]: m for m in data.get("member", [])}
        problems, per_value = [], {v["name"]: 0 for v in plan.values}
        for i in plan.children(ci):
            ln = plan.lines[i]
            want = {v["name"] for v in plan.values} if ln.effectivity == "ALL" else set(ln.values)
            for inst in rec["instances"].get(str(ln.row), []):
                if inst not in live:
                    problems.append(f"{ln.title}: instance {inst} is missing under {plan.configured_item}")
                    continue
                d = await self._call(self.mfg, "GET", f"/dsmfg:MfgItem/{pid}/dsmfg:MfgItemInstance/{inst}/dscfg:Filterable",
                                     params={"$fields": "dsmvcfg:attribute.effectivityContent"})
                eff = ((d.get("member") or [{}])[0].get("effectivityContent") or {}).get("Effectivity_Variant", "")
                got = set()
                if eff and "{" in eff:
                    got = {x.strip() for x in eff[eff.index("{") + 1: eff.rindex("}")].split(",") if x.strip()}
                if ln.effectivity == "ALL":
                    if eff:
                        problems.append(f"{ln.title}: expected no effectivity, found '{eff}'")
                    got = want
                elif got != want:
                    problems.append(f"{ln.title}: expected {sorted(want)}, found '{eff or 'none'}'")
                for v in got:
                    if v in per_value:
                        per_value[v] += 1
        extra = set(live) - {x for i in plan.children(ci) for x in rec["instances"].get(str(plan.lines[i].row), [])}
        if extra:
            problems.append(f"{len(extra)} instance(s) under {plan.configured_item} are not in the template")
        expected = plan.summary()["per_value"]
        for v, n in per_value.items():
            if n != expected[v]["instances"]:
                problems.append(f"value {v}: {n} instances resolve, the template expects {expected[v]['instances']}")
        result = {"ok": not problems, "instances_checked": len(live), "instances_per_value": per_value, "problems": problems}
        rec["validation"] = {"at": self._now(), **result}
        self._save()
        return result

    async def run(self) -> dict:
        try:
            await self.portfolio()
            await self.items()
            await self.instances()
            await self.configuration()
            await self.effectivity()
            result = await self.validate()
            self.rec["status"] = "done" if result["ok"] else "built with differences"
            self.rec["finished"] = self._now()
            self._save()
            return {"status": self.rec["status"], "run_record": str(self.record_path),
                    "model": self.rec["portfolio"], "root_item_id": self.rec["items"][str(self.plan.lines[0].row)]["id"],
                    "validation": result}
        except Exception as e:
            self.rec["status"] = "failed"
            self.rec["error"] = str(e)
            self._save()
            return {"status": "failed", "error": str(e), "run_record": str(self.record_path),
                    "resume": "Fix the cause, then call build_configured_mbom with resume_run set to this run record."}
