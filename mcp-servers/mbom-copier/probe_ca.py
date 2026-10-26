"""Compare a Change Action and an item's change data in the source and the target (read-only).

    python probe_ca.py "AJ MA 600"

Uses source.env and target.env. For the item with that title in each tenant it prints:
change control (Change Required), change impact, and every Change Action impacting it with
its state and proposed / realized changes. Paste the whole output back.
"""
import asyncio
import json
import sys
from pathlib import Path

import assoc as ax
import mbom_copy as mc

ROOT = Path(__file__).resolve().parent


def short(r, n=1500):
    return json.dumps(r, indent=1)[:n]


async def side(label, env, title):
    print(f"\n#################### {label} ({env})")
    creds = mc.load_profile(ROOT / env)
    mfg = mc.Api(mc.make_client(creds), label)
    ca = mc.Api(mc.make_client(creds, ax.SERVICES["ca"], "ca"), label)
    try:
        hits = [h for h in await mfg.search(title, 20) if h.get("title") == title]
        if not hits:
            print(f"no item titled {title!r}")
            return
        for it in hits:
            iid = it["id"]
            print(f"\n=== item {it.get('title')} {it.get('name')} rev {it.get('revision')} {it.get('state')} id {iid}")
            for what, path in (("change control", f"/dsmfg:MfgItem/{iid}/dslc:changeControl"),
                               ("change impact", f"/dsmfg:MfgItem/{iid}/dslc:changeImpact")):
                try:
                    print(f"--- {what}:\n{short(await mfg.call('GET', path), 1200)}")
                except Exception as e:
                    print(f"--- {what}: FAILED {str(e)[:300]}")
            try:
                imp = await mfg.call("GET", f"/dsmfg:MfgItem/{iid}/dslc:changeImpact")
                cas = {(o.get("referencedObject") or {}).get("identifier")
                       for m in mfg.members(imp) for o in (m.get("Impacting Objects") or [])}
            except Exception:
                cas = set()
            for cid in sorted(c for c in cas if c):
                try:
                    r = await ca.call("GET", f"/changeaction/{cid}", params={"$fields": "proposedChanges,realizedChanges,realizedActivities"})
                    keep = {k: r.get(k) for k in ("name", "title", "state", "policy", "proposedChanges", "realizedChanges", "realizedActivities")}
                    print(f"--- change action {cid}:\n{short(keep, 3000)}")
                except Exception as e:
                    print(f"--- change action {cid}: FAILED {str(e)[:300]}")
    finally:
        await mfg.c.aclose()
        await ca.c.aclose()


async def main(title, target_ca=None):
    await side("SOURCE", "source.env", title)
    await side("TARGET", "target.env", title)
    if target_ca:
        creds = mc.load_profile(ROOT / "target.env")
        ca = mc.Api(mc.make_client(creds, ax.SERVICES["ca"], "ca"), "TARGET")
        hits = await ca.call("GET", "/changeaction/search", params={"$searchStr": target_ca, "$top": 5})
        print(f"\n#################### TARGET CA search {target_ca!r}\n{short(hits, 800)}")
        for h in (hits.get("changeAction") or [])[:2]:
            r = await ca.call("GET", f"/changeaction/{h.get('identifier')}", params={"$fields": "proposedChanges,realizedChanges"})
            print(short({k: r.get(k) for k in ("name", "title", "state", "proposedChanges", "realizedChanges")}, 3000))
        await ca.c.aclose()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "AJ MA 600", sys.argv[2] if len(sys.argv) > 2 else None))
