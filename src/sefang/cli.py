"""Local maintenance commands.  Nothing here is reachable over HTTP."""
import argparse
import json
import sqlite3

from .config import Config

ACTIONS = ["serve", "entities", "avatars", "status", "metadata-pause", "metadata-resume", "fill-missing-covers", "translate", "translation-status", "translation-pause", "translation-resume"]


def main():
    parser = argparse.ArgumentParser(prog="sefang")
    parser.add_argument("action", choices=ACTIONS)
    parser.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1"])
    parser.add_argument("--port", type=int, default=18943)
    parser.add_argument("--include-missing", action="store_true", help="avatars: also retry actors without a portrait")
    parser.add_argument("--limit", type=int, default=0, help="fill-missing-covers: stop after this many works")
    parser.add_argument("--dry-run", action="store_true", help="fill-missing-covers: look up but do not install")
    args = parser.parse_args()
    config = Config.environment()
    if args.action in ("translate", "translation-status", "translation-pause", "translation-resume"):
        import asyncio
        from .localization import command
        action = {"translate": "batch", "translation-status": "status", "translation-pause": "pause", "translation-resume": "resume"}[args.action]
        print(json.dumps(asyncio.run(command(config, action, args.limit))))
        return
    if args.action == "serve":
        import uvicorn
        from .app import create_app
        uvicorn.run(create_app(config), host=args.host, port=args.port, access_log=False, log_level="warning", proxy_headers=False)
        return
    if args.action in ("metadata-pause", "metadata-resume"):
        with sqlite3.connect(config.db) as db:
            db.execute("UPDATE tg_catalog_control SET paused=? WHERE id=1", (int(args.action == "metadata-pause"),))
        print(json.dumps({"updated": True, "paused": args.action == "metadata-pause"}))
        return
    from .repository import Repository
    repo = Repository(config)
    try:
        if args.action == "entities":
            print(json.dumps({"entities": repo.sync_entities()}))
        elif args.action == "avatars":
            from .avatars import Portraits
            print(json.dumps(Portraits(repo).run(include_missing=args.include_missing), ensure_ascii=False))
        elif args.action == "status":
            from .avatars import Portraits
            with sqlite3.connect("file:" + str(config.db) + "?mode=ro", uri=True) as db:
                paused = bool(db.execute("SELECT paused FROM tg_catalog_control WHERE id=1").fetchone()[0])
            print(json.dumps({"videos": repo.videos(limit=1)["total"], "metadata_paused": paused,
                              "avatars": Portraits(repo).summary()}))
        elif args.action == "fill-missing-covers":
            from .backfill import fill_missing_covers
            print(json.dumps(fill_missing_covers(config, limit=args.limit, dry_run=args.dry_run), ensure_ascii=False))
    finally:
        repo.close()


if __name__ == "__main__":
    main()
