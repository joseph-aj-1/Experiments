"""Find out how the target tenant answers plant lookups (read-only).

    python probe_plant.py RSK

Uses target.env. Tries every plausible read-only route and prints, for each, whether it
answered and the start of the answer. Paste the whole output back.
"""
import asyncio
import json
import sys
from pathlib import Path

import assoc as ax
import mbom_copy as mc

ROOT = Path(__file__).resolve().parent


def short(r, n=700):
    try:
        return json.dumps(r)[:n]
    except Exception:
        return str(r)[:n]


async def main(name):
    creds = mc.load_profile(ROOT / "target.env")
    space = mc.Api(mc.make_client(creds, [("3DSpace", "{3DSpace}")], "space"), "target")
    srch = mc.Api(mc.make_client(creds, ax.SERVICES["search"], "search"), "target")
    print("3DSpace :", space.c.base_url)
    print("3DSearch:", srch.c.base_url)
    tenant = creds.tenant or ""

    gets = [
        ("org collection, searchStr", "/resources/v1/modeler/organizations", {"$searchStr": name}),
        ("org collection", "/resources/v1/modeler/organizations", None),
        ("org collection, type Plant", "/resources/v1/modeler/organizations", {"type": "Plant"}),
        ("org search (top)", "/resources/v1/modeler/organizations/search", {"$searchStr": name, "$top": 5}),
        ("pno organization list", "/resources/modeler/pno/organization", None),
        ("pno organization, name", f"/resources/modeler/pno/organization/{name}", None),
        ("pno person (my orgs)", "/resources/modeler/pno/person", {"current": "true", "select": "organizations"}),
        ("mfg responsibility search", "/resources/v1/modeler/dsmfg/dsmfg:MfgResponsibility/search", {"$searchStr": name}),
    ]
    for label, path, params in gets:
        try:
            r = await space.call("GET", path, params=params)
            print(f"\n--- GET {label}: OK\n{short(r)}")
        except Exception as e:
            print(f"\n--- GET {label}: FAILED {str(e)[:300]}")

    queries = [f"Org:{name}", name, f'"{name}"', f"[ds6w:label]:{name}", f'[ds6w:type]:"Plant"', f"[ds6w:type]:Plant AND {name}"]
    for q in queries:
        for src in (["3dspace"], None):
            body = {"label": "mbom-copier", "locale": "en", "select_predicate": ["ds6w:label", "ds6w:type", "physicalid"],
                    "select_file": [], "query": q, "order_field": "relevance", "order_dir": "desc",
                    "nresults": 5, "start": "0", "tenant": tenant}
            if src:
                body["source"] = src
            try:
                r = await srch.call("POST", "/search", json=body)
                n = len(r.get("results") or []) if isinstance(r, dict) else "?"
                print(f"\n--- 3DSearch {q!r} source={src}: OK, {n} results\n{short(r, 500)}")
            except Exception as e:
                print(f"\n--- 3DSearch {q!r} source={src}: FAILED {str(e)[:300]}")
    await space.c.aclose()
    await srch.c.aclose()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "RSK"))
