"""Float on Release automatic agent (no MCP client needed).

    python agent.py                      # watch the EIF listener's events folder
    python agent.py --event FILE.json    # process one saved EIF message, then exit
    python agent.py --item "AJ PP 301"   # dry-run preview for one item, then exit
    python agent.py --item ID --apply    # real run for one item (ignores dry_run)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging

from float_on_release.core import FloatOnRelease
from float_on_release.settings import load_settings
from float_on_release.watcher import handle_message, watch

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--event", help="Process one saved EIF message file")
    p.add_argument("--item", help="Physical ID or title of a released item")
    p.add_argument("--apply", action="store_true", help="With --item: really replace")
    a = p.parse_args()

    settings = load_settings()
    engine = FloatOnRelease(settings)
    try:
        if a.event:
            with open(a.event, encoding="utf-8") as f:
                out = await handle_message(json.load(f), engine, settings, label=a.event)
        elif a.item:
            out = await engine.run(await engine.resolve(a.item), dry_run=not a.apply, trigger="cli")
        else:
            await watch(settings, engine)
            return
        print(json.dumps(out, indent=2))
    finally:
        await engine.aclose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
