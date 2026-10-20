"""Configured MBOM Builder: MCP server for Claude Desktop.

Builds a configured Manufacturing BOM in 3DEXPERIENCE from an Excel template:
Portfolio model version + variant + values, Manufacturing Items, instances,
configuration context, and variant effectivity, then reads it all back.

Tools
  new_configured_mbom_template(path)            blank template to fill in
  preview_configured_mbom(file_path)            checks + exact creation plan (no changes)
  build_configured_mbom(file_path, confirm, resume_run)
  validate_configured_mbom(run_record)          read back and compare again
  list_configured_mbom_runs()

Run:  python server.py   (stdio, started by Claude Desktop)
"""
from __future__ import annotations

import json
import logging
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from fastmcp import FastMCP  # noqa: E402

from cmb.builder import RUNS, Builder, BuildError, file_sha  # noqa: E402
from cmb.template import make_template, plan_report, read_template  # noqa: E402

logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

mcp = FastMCP("Configured MBOM Builder", instructions=(
    "Builds configured MBOMs in 3DEXPERIENCE from the Configured MBOM Excel template. "
    "Always run preview_configured_mbom first and show the user the plan and any problems. "
    "Only call build_configured_mbom with confirm=true after the user has approved that preview."))


def _path(p: str) -> Path:
    path = Path(p).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"{path} not found")
    return path


@mcp.tool
def new_configured_mbom_template(path: str) -> dict:
    """Create a blank Configured MBOM template (.xlsx) at `path` for the user to fill in.
    An example filled in for the Rosemount R-648 housing is in the server's templates folder."""
    out = Path(path).expanduser()
    if out.suffix.lower() != ".xlsx":
        out = out.with_suffix(".xlsx")
    if out.exists():
        raise FileExistsError(f"{out} already exists; choose another name")
    blank = ROOT / "templates" / "Configured_MBOM_Template.xlsx"
    if blank.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(blank, out)
    else:
        make_template(out)
    return {"created": str(out), "example": str(ROOT / "templates" / "Example_R648_Housing.xlsx")}


@mcp.tool
async def preview_configured_mbom(file_path: str) -> dict:
    """Check a filled Configured MBOM template and show exactly what would be created:
    model version, variant and values, items, instances per line, which items get the model,
    and the effectivity per line, plus how many lines/instances each variant value resolves to.
    Also checks the tenant: the model version title must not exist yet, and Existing item IDs must exist.
    Changes nothing."""
    path = _path(file_path)
    plan = read_template(path)
    report = plan_report(plan)
    tenant_problems = []
    try:
        b = Builder.__new__(Builder)        # clients only, no run record
        from cmb.builder import _clients
        b.mfg, b.pfl, b.plan = *_clients(), plan
        existing = await b.model_title_exists() if plan.model_title else []
        if existing:
            tenant_problems.append(f"A model version titled '{plan.model_title}' already exists "
                                   f"({existing[0].get('name')}). Change the title on the Model tab.")
        tenant_problems += await b.check_existing_items()
    except Exception as e:  # report, but still return the sheet checks
        tenant_problems.append(f"Could not check the tenant: {e}")
    report["problems"] += tenant_problems
    report["ok"] = not report["problems"]
    report["next_step"] = ("Ready to build: call build_configured_mbom with confirm=true once the user approves."
                           if report["ok"] else "Fix the problems listed, save the workbook, and preview again.")
    return report


@mcp.tool
async def build_configured_mbom(file_path: str, confirm: bool = False, resume_run: str = "") -> dict:
    """Build the configured MBOM described by the template in 3DEXPERIENCE.
    Requires confirm=true, which the user must approve after seeing preview_configured_mbom.
    Every created object is recorded in a run record (runs folder); if a build fails part-way,
    call again with resume_run=<run record path> to continue without creating duplicates."""
    path = _path(file_path)
    plan = read_template(path)
    report = plan_report(plan)
    if not plan.ok:
        return {"status": "not built", "problems": report["problems"]}
    if not confirm:
        return {"status": "not built", "reason": "confirm=true is required. Run preview_configured_mbom, "
                "show the plan to the user, and build only after they approve.", "summary": report["summary"]}
    record = None
    if resume_run:
        record = _path(resume_run)
        rec = json.loads(record.read_text())
        if rec.get("template_sha256") != file_sha(str(path)):
            return {"status": "not built", "reason": "The template changed since that run started. "
                    "Resume only with the same workbook, or start a new build with a new model version title."}
    builder = Builder(plan, record)
    if not resume_run:
        if await builder.model_title_exists():
            return {"status": "not built", "reason": f"Model version '{plan.model_title}' already exists."}
        problems = await builder.check_existing_items()
        if problems:
            return {"status": "not built", "problems": problems}
    return await builder.run()


@mcp.tool
async def validate_configured_mbom(run_record: str) -> dict:
    """Read a built configured MBOM back from 3DEXPERIENCE and compare it with its template again
    (instances present, effectivity per instance, instances per variant value)."""
    record = _path(run_record)
    rec = json.loads(record.read_text())
    plan = read_template(_path(rec["template"]))
    return await Builder(plan, record).validate()


@mcp.tool
def list_configured_mbom_runs(limit: int = 10) -> list[dict]:
    """Recent builds, newest first: model title, status, template, record path."""
    RUNS.mkdir(exist_ok=True)
    out = []
    for f in sorted(RUNS.glob("*.json"), reverse=True)[:limit]:
        try:
            r = json.loads(f.read_text())
            out.append({"run_record": str(f), "model_title": r.get("model_title"), "status": r.get("status"),
                        "template": r.get("template"), "started": r.get("started"),
                        "validation_ok": (r.get("validation") or {}).get("ok")})
        except Exception:
            continue
    return out


if __name__ == "__main__":
    mcp.run()
