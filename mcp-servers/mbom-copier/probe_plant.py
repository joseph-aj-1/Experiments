"""Show what the target tenant's plant searches return (read-only).

    python probe_plant.py RSK SG2

Uses target.env. Prints the raw answers of the organizations search and of 3DSearch
for each name, so the plant lookup can be matched to what the tenant really returns.
"""
import asyncio
import json
import sys
from pathlib import Path

import assoc as ax
import mbom_copy as mc

ROOT = Path(__file__).resolve().parent


async def main(names):
    creds = mc.load_profile(ROOT / "target.env")
    org = mc.Api(mc.make_client(creds, ax.SERVICES["org"], "org"), "target")
    srch = mc.Api(mc.make_client(creds, ax.SERVICES["search"], "search"), "target")
    print("organizations base:", org.c.base_url)
    print("3DSearch base:     ", srch.c.base_url)
    for name in names:
        print(f"\n===== {name}")
        for label, coro in (
            ("organizations search", org.call("GET", "/organizations/search", params={"$searchStr": name, "$top": 10})),
            ("3DSearch Org:", srch.call("POST", "/search", json={
                "label": "mbom-copier", "locale": "en", "select_predicate": ["ds6w:label", "ds6w:type", "physicalid", "ds6w:identifier"],
                "select_file": [], "query": f"Org:{name}", "order_field": "relevance", "order_dir": "desc",
                "nresults": 10, "start": "0", "source": ["3dspace"], "tenant": creds.tenant or ""})),
            ("3DSearch type Plant", srch.call("POST", "/search", json={
                "label": "mbom-copier", "locale": "en", "select_predicate": ["ds6w:label", "ds6w:type", "physicalid", "ds6w:identifier"],
                "select_file": [], "query": f'[ds6w:type]:"Plant" AND "{name}"', "order_field": "relevance", "order_dir": "desc",
                "nresults": 10, "start": "0", "source": ["3dspace"], "tenant": creds.tenant or ""})),
        ):
            try:
                r = await coro
                print(f"--- {label}: OK")
                print(json.dumps(r, indent=1)[:2500])
            except Exception as e:
                print(f"--- {label}: FAILED {str(e)[:400]}")
    await org.c.aclose()
    await srch.c.aclose()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or ["RSK"]))
