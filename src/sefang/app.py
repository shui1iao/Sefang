"""Authenticated private website; account bootstrap remains local-only."""
from contextlib import asynccontextmanager
import asyncio
import hashlib
import logging
import re

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse
from .history import HistoryStore, router as history_router
from .auth import AuthStore, router as auth_router
from .access import Boundary, PlaybackControl, router as access_router
from filelock import FileLock
from starlette.responses import FileResponse, HTMLResponse, Response
from starlette.staticfiles import StaticFiles

from .avatars import Portraits
from .config import Config
from .grouping import SORT_MODES
from .repository import PUBLIC_KINDS, Repository
from .streaming import router as stream_router
from .tg.link import TgLink
from .tg.owner import ChannelOwner
from .tg.works import WorkFiller
from .thumbnails import DECODE_SECONDS, inspect_thumbnail
from .localization import Worker as TranslationWorker

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")


def create_app(config: Config, link_factory=TgLink):
    repo = Repository(config)
    owner = None if config.offline else ChannelOwner(config, link_factory=link_factory)
    if owner is not None and {c["id"] for c in owner.channels()} != set(config.channels):
        raise ValueError("private channel allowlist mismatch")
    filler = WorkFiller(owner) if owner is not None else None
    lease = FileLock(config.data / "state/se-video-owner.lock")
    background: list[asyncio.Task] = []
    portraits: list[Portraits] = []
    thumbnail_decode_gate = asyncio.Semaphore(2)
    translator = None if config.offline else TranslationWorker(config)

    async def keep_entities():
        seen = None
        while True:
            try:
                await asyncio.to_thread(repo.refresh)
                if repo.entity_generation != seen:
                    seen = repo.entity_generation
                    worker = Portraits(repo)
                    portraits[:] = [worker]
                    job = asyncio.create_task(asyncio.to_thread(worker.run))
                    try:
                        await asyncio.shield(job)
                    except asyncio.CancelledError:
                        worker.stop.set()
                        await job
                        raise
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(30)

    @asynccontextmanager
    async def lifespan(app):
        repo.sync_entities()
        if owner is not None:
            lease.acquire(timeout=0)
            logging.getLogger("telethon").setLevel(logging.WARNING)
            owner.on_change = filler.poke
            await owner.start()
            filler.start()
            background.append(asyncio.create_task(keep_entities()))
            background.append(asyncio.create_task(translator.background()))
        try:
            yield
        finally:
            if translator is not None:
                translator.stop.set()
            for worker in portraits:
                worker.stop.set()
            for task in background:
                task.cancel()
            if background:
                await asyncio.gather(*background, return_exceptions=True)
            if owner is not None:
                await filler.stop()
                await owner.stop()
                lease.release()
            repo.close()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.config, app.state.repository, app.state.telegram, app.state.filler = config, repo, owner, filler

    auth = AuthStore(config.data / "state/auth/accounts.sqlite3")
    app.state.auth = auth
    app.state.password_gate = asyncio.Semaphore(2)
    app.state.playbacks = PlaybackControl(auth)
    app.add_middleware(Boundary, store=auth, csp=CSP)
    app.state.history = HistoryStore(config.data / "state/history/history.sqlite3")
    app.include_router(history_router)
    app.include_router(auth_router)
    app.include_router(access_router)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, error):
        # FastAPI's default validation response reflects raw passwords and request bodies.
        return JSONResponse({"detail": "输入无效，请检查格式和必填项"}, status_code=422)

    @app.exception_handler(Exception)
    async def internal_error(request, error):
        return JSONResponse({"detail": "请求未完成"}, status_code=500,
                            headers={"Cache-Control": "private, no-store", "Vary": "Cookie", "Content-Security-Policy": CSP})

    @app.get("/healthz")
    def health():
        return {"ok": True}

    @app.get("/api/videos")
    def videos(q: str = Query("", max_length=300), actor: str = Query("", max_length=24), studio: str = Query("", max_length=24),
               category: str = Query("", max_length=24),
               sort: str = Query("newest", pattern="^("+"|".join(SORT_MODES)+")$"),
               page: int = Query(1, ge=1, le=100000), limit: int = Query(36, ge=1, le=60)):
        return repo.videos(q=q, actor=actor, studio=studio, category=category, sort=sort, page=page, limit=limit)

    @app.get("/api/entities/{kind}")
    def entities(kind: str, q: str = Query("", max_length=200), page: int = Query(1, ge=1, le=10000),
                 limit: int = Query(40, ge=1, le=100)):
        if kind not in PUBLIC_KINDS:
            raise HTTPException(404)
        return repo.entities(kind, q, page, limit)

    @app.get("/api/entities/{kind}/{ident}")
    def entity(kind: str, ident: str):
        if kind not in PUBLIC_KINDS:
            raise HTTPException(404)
        row = repo.entity(kind, ident)
        if not row:
            raise HTTPException(404, "此分类未取得")
        return row

    @app.get("/api/videos/{cid}/{mid}")
    def detail(cid: int, mid: int):
        if cid not in config.channels or not 0 < mid < 2 ** 53:
            raise HTTPException(404, "视频未取得或不在允许频道内")
        result = repo.detail(cid, mid)
        if not result:
            raise HTTPException(404, "视频未取得或不在允许频道内")
        return result

    @app.get("/api/videos/{cid}/{mid}/related")
    def related(cid: int, mid: int):
        result = repo.related(cid, mid)
        if result is None:
            raise HTTPException(404)
        return result

    @app.api_route("/api/videos/{cid}/{mid}/cover", methods=["GET", "HEAD"])
    def cover(cid: int, mid: int):
        row = repo.raw(cid, mid)
        if not row:
            raise HTTPException(404)
        name = row.get("cover_file") or ""
        if not row.get("identity") or name != hashlib.sha256(row["identity"].encode()).hexdigest() + ".cover":
            raise HTTPException(404)
        path = config.covers / name
        if not path.is_file() or path.stat().st_size > 8 * 1048576:
            raise HTTPException(404)
        with repo.read() as db:
            mime = db.execute("SELECT cover_mime FROM tg_work WHERE identity=?", (row["identity"],)).fetchone()[0]
        return FileResponse(path, media_type=mime, headers={"Cache-Control": "private, no-store"})

    @app.api_route("/api/actors/{ident}/image", methods=["GET", "HEAD"])
    def avatar_image(ident: str):
        actor = repo.entity("actors", ident)
        if not actor:
            raise HTTPException(404)
        ident = actor["id"]
        with repo.local() as db:
            row = db.execute("SELECT avatar_file,avatar_mime FROM entity WHERE id=? AND kind='actors'", (ident,)).fetchone()
        if not row or row[0] != ident + ".img":
            raise HTTPException(404)
        path = repo.root / "avatars" / row[0]
        if not path.is_file() or path.stat().st_size > 2 * 1048576:
            raise HTTPException(404)
        return FileResponse(path, media_type=row[1], headers={"Cache-Control": "private, no-store"})

    @app.get("/api/videos/{cid}/{mid}/thumbnail")
    async def thumbnail(cid: int, mid: int, skip_cover: bool = False):
        row = repo.raw(cid, mid)
        if not row:
            raise HTTPException(404)
        # Formal covers bypass the Telegram-only empty/black thumbnail check.
        if not skip_cover and repo.dto(row)["has_cover"]:
            return cover(cid, mid)
        reason = "unavailable"
        try:
            if owner is not None:
                data = await asyncio.wait_for(owner.thumbnail(cid, mid), 20)
                async with thumbnail_decode_gate:
                    mime, reason = await asyncio.wait_for(
                        asyncio.to_thread(inspect_thumbnail, data), DECODE_SECONDS)
                if mime:
                    return Response(data, media_type=mime, headers={"Cache-Control": "no-store"})
        except Exception:
            reason = "unavailable"
        # A successful SVG would suppress Artwork.onError and its explicit text placeholder.
        return Response('{"detail":"缩略图未取得","reason":"' + reason + '"}', status_code=404,
                        media_type="application/json", headers={"Cache-Control": "no-store"})

    app.include_router(stream_router)
    if config.static.is_dir():
        app.mount("/assets", StaticFiles(directory=config.static / "assets"), name="assets")

    @app.api_route("/history", methods=["GET", "HEAD"])
    @app.api_route("/login", methods=["GET", "HEAD"])
    @app.api_route("/admin/accounts", methods=["GET", "HEAD"])
    @app.api_route("/", methods=["GET", "HEAD"])
    @app.api_route("/actors", methods=["GET", "HEAD"])
    @app.api_route("/studios", methods=["GET", "HEAD"])
    @app.api_route("/categories", methods=["GET", "HEAD"])
    @app.api_route("/actors/{ident}", methods=["GET", "HEAD"])
    @app.api_route("/studios/{ident}", methods=["GET", "HEAD"])
    @app.api_route("/categories/{ident}", methods=["GET", "HEAD"])
    @app.api_route("/watch/{cid}/{mid}", methods=["GET", "HEAD"])
    def page(request: Request, ident: str = "", cid: str = "", mid: str = ""):
        if ident and not re.fullmatch("[0-9a-f]{24}", ident):
            raise HTTPException(404)
        if cid and (not cid.isdecimal() or not mid.isdecimal() or int(cid) not in config.channels or not 0 < int(mid) < 2 ** 53):
            raise HTTPException(404)
        path = config.static / "index.html"
        if not path.is_file():
            return HTMLResponse("<!doctype html><title>Sefang</title><p>静态资源未构建</p>", status_code=503)
        return FileResponse(path, media_type="text/html", headers={"Cache-Control": "no-store"})

    return app
