"""One-off repair: find covers for works that have a reliable number but no installed cover.

Only cover columns of rows that currently lack a cover are written; metadata,
sources and existing covers are left exactly as they are.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .catalog.chain import lookup
from .catalog.web import HoldBook, Spacer
from .tg.index import ChannelIndex
from .tg.works import CoverShelf, cover_name

SKIP_FAMILIES = ("kmib", "other", "unknown")


def missing_cover_rows(index: ChannelIndex, covers_root: Path, channels) -> list[dict]:
    marks = ",".join("?" * len(channels))
    with index.session() as db:
        rows = [dict(r) for r in db.execute(
            f"SELECT w.identity,w.code,w.content_type,w.cover_file,w.cover_state FROM tg_work w WHERE EXISTS(SELECT 1 FROM "
            f"tg_identification i WHERE i.identity=w.identity AND i.state='identified' AND i.channel_id IN ({marks})) ORDER BY w.code",
            list(channels))]
    out = []
    for r in rows:
        if r["content_type"] in SKIP_FAMILIES:
            continue
        name = cover_name(r["identity"])
        if r["cover_file"] == name and (covers_root / name).is_file():
            continue
        out.append(r)
    return out


def fill_missing_covers(config, *, limit=0, dry_run=False) -> dict:
    index = ChannelIndex(config.db)
    root = Path(config.candidate_root) / "telegram-catalog"
    shelf = CoverShelf(root / "covers", index)
    holds, spacer = HoldBook(root / "source-state"), Spacer()
    todo = missing_cover_rows(index, shelf.root, config.channels)
    if limit:
        todo = todo[:limit]
    report = {"candidates": len(todo), "installed": [], "still_missing": {}}
    for row in todo:
        with index.session() as db:
            hints = [str(x) for h in db.execute(
                "SELECT v.title,v.caption FROM tg_video v JOIN tg_identification i ON i.channel_id=v.channel_id AND "
                "i.message_id=v.message_id WHERE i.identity=? LIMIT 3", (row["identity"],)) for x in h]
        try:
            result = lookup(row["code"], hints, holds=holds, spacer=spacer)
        except Exception as error:
            report["still_missing"][row["code"]] = "error:" + type(error).__name__
            continue
        if result.cover is None:
            why = result.cover_state if result.found else ("no catalogue record" if not result.problems else
                                                           "sources unavailable: " + ",".join(p["source"] for p in result.problems))
            report["still_missing"][row["code"]] = why
            if not dry_run:
                with index.session() as db:
                    db.execute("UPDATE tg_work SET cover_state=?,cover_checked_at=? WHERE identity=? AND (cover_file='' OR cover_file IS NULL)",
                               (result.cover_state if result.cover_state != "available" else "not_found", time.time(), row["identity"]))
            continue
        data, url, size = result.cover
        if dry_run:
            report["installed"].append({"code": row["code"], "source": url, "size": list(size), "dry_run": True})
            continue
        if shelf.has(row["identity"]):
            continue
        shelf.put(row["identity"], data, url, size)
        report["installed"].append({"code": row["code"], "source": url, "size": list(size)})
    report["installed_count"] = len(report["installed"])
    return json.loads(json.dumps(report))
