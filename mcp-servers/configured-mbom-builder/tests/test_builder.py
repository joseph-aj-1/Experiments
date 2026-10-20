"""Offline tests: python -m pytest tests  (or python tests/test_builder.py)."""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cmb.builder import Builder, effectivity_xml  # noqa: E402
from cmb.template import read_template  # noqa: E402
from mock_tenant import MockTenant  # noqa: E402

T = ROOT / "templates"


def build(template, tenant, record=None):
    plan = read_template(T / template)
    mfg, pfl = tenant.clients()
    b = Builder(plan, record, mfg=mfg, pfl=pfl)
    return b, asyncio.run(b.run())


def test_r648_full_build():
    t = MockTenant()
    b, res = build("Example_R648_Housing.xlsx", t)
    assert res["status"] == "done", res
    assert len(t.items) == 29 and len(t.instances) == 33
    assert len(t.effectivity) == 10
    assert res["validation"]["instances_per_value"] == {"1143": 25, "1144": 25, "1145": 25}
    assert len(t.attached) == 4 and list(t.criteria.values()) == [["Variant"]]
    assert "{1143,1144}" in json.dumps(t.effectivity)


def test_resume_after_failure():
    t = MockTenant(fail_after=20)
    b, res = build("Example_R648_Housing.xlsx", t)
    assert res["status"] == "failed"
    made = len(t.items)
    t.fail_after = None
    b2, res2 = build("Example_R648_Housing.xlsx", t, record=b.record_path)
    assert res2["status"] == "done", res2
    assert len(t.items) == 29 and len(t.instances) == 33 and len(t.models) == 1, (made, len(t.items))


def test_mini():
    t = MockTenant()
    _, res = build("Mini_Test.xlsx", t)
    assert res["status"] == "done", res
    assert res["validation"]["instances_per_value"] == {"A": 3, "B": 3}


def test_xml():
    x = effectivity_xml("MV-1", "VAR-1", ["VV-1", "VV-2"])
    assert "<OR>" in x and x.count('Name="VAR-1"') == 2


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("passed", name)
