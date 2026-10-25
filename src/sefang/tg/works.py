"""Background enrichment of work rows (metadata + cover) with pause/resume and retry spacing.

Only rows still waiting (`pending`) or due for their single retry are picked up;
finished rows are never fetched again by this worker.  A file lease makes sure
only one process runs it, and the pause flag lives in the index database so the
private CLI can flip it.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import threading
import time
from pathlib import Path

from filelock import FileLock, Timeout
from PIL import Image

from ..catalog.chain import lookup
from ..catalog.web import HoldBook, Spacer, Stopped
from .index import lock_down_dir

COVER_BUDGET = 512 * 1024 * 1024
COVER_FILES = 2048
COVER_MAX = 8 * 1048576
TRIES = 2
RETRY_GAP = 30


def cover_name(identity: str) -> str:
    return hashlib.sha256(identity.encode()).hexdigest() + ".cover"


def source_rank(source: str) -> int:
    # Provenance, never filename heuristics. Legacy verified26 already use this kind.
    try:
        value=json.loads(source)
        if isinstance(value,dict) and value.get('kind')=='channel_photo':return 1
    except (ValueError,TypeError):pass
    return 2


def _charge(path: Path) -> int:
    st = path.stat()
    return max(st.st_size, st.st_blocks * 512)


class CoverShelf:
    """The bounded directory of installed cover files."""

    def __init__(self, root: Path, index, *, budget=COVER_BUDGET, files=COVER_FILES):
        self.root = lock_down_dir(Path(root))
        self.index, self.budget, self.files = index, budget, files
        self.lock = FileLock(self.root / "catalog.lock")
        with self.lock:
            for leftover in self.root.glob("*.part"):
                leftover.unlink(missing_ok=True)
            self._make_room(0, 0)
        (self.root / "catalog.lock").chmod(0o600)

    def _entries(self):
        items = []
        for p in self.root.glob("*.cover"):
            try:
                items.append((p.stat().st_mtime, p, _charge(p)))
            except FileNotFoundError:
                pass
        return sorted(items, key=lambda x: x[0])

    def _make_room(self, incoming: int, count: int, keep=None) -> None:
        items = self._entries()
        used, n = sum(c for _, _, c in items), len(items)
        with self.index.session() as db:
            for _, path, cost in items:
                if used + incoming <= self.budget and n + count <= self.files:
                    break
                if path == keep:continue
                path.unlink(missing_ok=True)
                used, n = used - cost, n - 1
                db.execute("UPDATE tg_work SET cover_state='evicted',cover_file='' WHERE cover_file=?", (path.name,))

    def usage(self) -> dict:
        with self.lock:
            items = self._entries()
        return {"bytes": sum(c for _, _, c in items), "files": len(items), "limit": self.budget, "max_files": self.files}

    def has(self, identity: str) -> bool:
        with self.index.session() as db:
            row = db.execute("SELECT cover_file FROM tg_work WHERE identity=?", (identity,)).fetchone()
        name = cover_name(identity)
        return bool(row and row[0] == name and (self.root / name).is_file())

    def rank(self, identity: str) -> int:
        if not self.has(identity):return 0
        with self.index.session() as db:
            row=db.execute('SELECT cover_source FROM tg_work WHERE identity=?',(identity,)).fetchone()
        return source_rank(row[0]) if row else 0

    def put(self, identity: str, data: bytes, source: str, size) -> str:
        if not data or len(data) > COVER_MAX or len(data) > self.budget:
            raise ValueError("cover too large")
        with Image.open(io.BytesIO(data)) as im:
            if im.format not in ("JPEG", "PNG", "WEBP") or getattr(im, "is_animated", False):
                raise ValueError("unsupported cover format")
            if im.width * im.height > 40_000_000 or im.size != tuple(size):
                raise ValueError("cover size mismatch")
            im.load()
            if source_rank(source)==1 and (im.width<240 or im.convert('RGB').getextrema()==((0,0),(0,0),(0,0))):
                raise ValueError('unusable channel photo')
            mime, (w, h) = Image.MIME[im.format], im.size
        name = cover_name(identity)
        path = self.root / name
        part = path.with_name(name + ".part")
        with self.lock:
            # Existing good same/higher-tier art wins. Validate new bytes before any eviction.
            if self.rank(identity)>=source_rank(source):return name
            old_cost=_charge(path) if path.is_file() else 0
            incoming=max(len(data), -(-len(data) // 4096) * 4096)
            self._make_room(max(0,incoming-old_cost), 0 if old_cost else 1, keep=path)
            fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                with os.fdopen(fd, "wb") as out:
                    out.write(data)
                    out.flush()
                    os.fsync(out.fileno())
                os.replace(part, path)
                path.chmod(0o600)
            finally:
                part.unlink(missing_ok=True)
            with self.index.session() as db:
                db.execute("UPDATE tg_work SET cover_state='installed',cover_file=?,cover_mime=?,cover_source=?,"
                           "cover_width=?,cover_height=?,cover_checked_at=? WHERE identity=?",
                           (name, mime, source, w, h, time.time(), identity))
        return name


class WorkFiller:
    def __init__(self, owner, *, fetch=lookup, workers=2):
        self.owner = owner
        self.index = owner.index
        root = lock_down_dir(Path(owner.config.candidate_root) / "telegram-catalog")
        self.shelf = CoverShelf(root / "covers", self.index)
        self.holds = HoldBook(lock_down_dir(root / "source-state"))
        self.spacer = Spacer()
        self.fetch = fetch
        self.workers = workers
        self.halt = threading.Event()
        self.kick = asyncio.Event()
        self.photo_gate = asyncio.Lock()
        self.tasks: list[asyncio.Task] = []
        self.lease = FileLock(root / "worker.lock")
        self.leased = False

    def start(self) -> None:
        if self.tasks or not self.owner.channels():
            return
        try:
            self.lease.acquire(timeout=0)
        except Timeout:
            return
        self.leased = True
        with self.index.session() as db:
            db.execute("UPDATE tg_work SET state='pending' WHERE state='processing'")
        self.halt.clear()
        self.tasks = [asyncio.create_task(self._loop()) for _ in range(self.workers)]
        self.kick.set()

    def poke(self) -> None:
        if not self.tasks:
            self.start()
        self.kick.set()

    async def stop(self) -> None:
        self.halt.set()
        self.kick.set()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
            self.tasks = []
        if self.leased:
            self.lease.release()
            self.leased = False

    def _next(self):
        allowed = [c["id"] for c in self.owner.channels()]
        if not allowed or self.halt.is_set():
            return None
        marks = ",".join("?" * len(allowed))
        with self.index.session() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT paused FROM tg_catalog_control WHERE id=1").fetchone()[0]:
                return None
            row = db.execute(
                f"SELECT w.* FROM tg_work w WHERE EXISTS(SELECT 1 FROM tg_identification i WHERE i.identity=w.identity "
                f"AND i.channel_id IN ({marks})) AND (w.state='pending' OR (w.state<>'processing' AND w.attempts<? AND w.next_retry>0 AND "
                f"w.next_retry<=?)) ORDER BY w.attempts,w.code LIMIT 1", [*allowed, TRIES, time.time()]).fetchone()
            if row is None:
                return None
            db.execute("UPDATE tg_work SET state='processing',attempts=attempts+1 WHERE identity=?", (row["identity"],))
            hints = db.execute("SELECT v.title,v.caption FROM tg_video v JOIN tg_identification i ON i.channel_id=v.channel_id "
                               "AND i.message_id=v.message_id WHERE i.identity=? LIMIT 3", (row["identity"],)).fetchall()
        return dict(row), [str(x) for h in hints for x in h]

    def _fill(self, job) -> None:
        work, hints = job
        identity = work["identity"]
        try:
            result = self.fetch(work["code"], hints, holds=self.holds, spacer=self.spacer, stop=self.halt,
                                want_cover=self.shelf.rank(identity)<2)
            if self.halt.is_set():
                raise Stopped()
            fields = json.loads(work["metadata"] or "{}")
            fields.update({k: v for k, v in result.fields.items() if v})
            sources = result.sources or json.loads(work["sources"] or "[]")
            state = result.state
            if state in ("not_found", "temporary_error") and any(fields.get(k) for k in ("title", "performers", "studio", "release_date", "tags")):
                state = "partial"
            cover_state = result.cover_state
            if result.cover:
                data, url, size = result.cover
                try:
                    self.shelf.put(identity, data, url, size)
                    cover_state = "installed"
                except (OSError, ValueError):
                    cover_state = "temporary_error"
            elif work["cover_file"] and self.shelf.has(identity):
                cover_state = "installed"
            # A usable cached TG cover must survive failed downloads and still retain the
            # original finite catalogue retry, independently of its installed cover state.
            again = (state == "temporary_error" or cover_state == "temporary_error" or result.cover_state == 'temporary_error') and work["attempts"] + 1 < TRIES
            if self.shelf.has(identity):cover_state='installed' 
            with self.index.session() as db:
                db.execute("UPDATE tg_work SET state=?,metadata=?,sources=?,checked_at=?,next_retry=?,error=?,cover_state=? "
                           "WHERE identity=?", (state, json.dumps(fields, ensure_ascii=False), json.dumps(sources, ensure_ascii=False),
                                                time.time(), time.time() + RETRY_GAP if again else 0,
                                                json.dumps(result.problems), cover_state, identity))
        except Stopped:
            with self.index.session() as db:
                db.execute("UPDATE tg_work SET state='pending',attempts=max(attempts-1,0) WHERE identity=?", (identity,))
        except Exception as error:
            with self.index.session() as db:
                db.execute("UPDATE tg_work SET state='temporary_error',error=?,next_retry=? WHERE identity=?",
                           (type(error).__name__, time.time() + RETRY_GAP if work["attempts"] + 1 < TRIES else 0, identity))

    def _next_photo(self):
        allowed=[c['id'] for c in self.owner.channels()]
        if not allowed or self.halt.is_set():return None
        marks=','.join('?'*len(allowed))
        with self.index.session() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT paused FROM tg_catalog_control WHERE id=1').fetchone()[0]:return None
            row=db.execute(f"SELECT p.identity FROM tg_cover_pending p JOIN tg_work w USING(identity) "
                "WHERE w.state NOT IN ('pending','processing') AND EXISTS(SELECT 1 FROM tg_identification i "
                f"WHERE i.identity=p.identity AND i.channel_id IN ({marks})) ORDER BY p.identity LIMIT 1",allowed).fetchone()
            if row:
                db.execute('DELETE FROM tg_cover_pending WHERE identity=?',(row[0],))
                return row[0]
        return None

    async def _photo_cover(self, identity):
        # Same existing work loops, not a new worker/sweep. Queue entries only come
        # from genuinely observed normal source changes. Catalogue pending runs first.
        async with self.photo_gate:
            if self.halt.is_set() or self.shelf.has(identity):return
            with self.index.session() as db:
                work=db.execute('SELECT state FROM tg_work WHERE identity=?',(identity,)).fetchone()
            if not work or work[0] in ('pending','processing'):return
            candidates=self.index.photo_candidates(identity,[c['id'] for c in self.owner.channels()])
            if not candidates:return
            candidate=candidates[0]  # at most one bounded photo attempt per source event/job
            try:
                result=await self.owner.cover_photo(candidate,COVER_MAX)
                if not result or self.halt.is_set() or self.shelf.has(identity):return
                data,source=result
                if candidate not in self.index.photo_candidates(identity,[candidate['channel_id']]):return
                def save():
                    with Image.open(io.BytesIO(data)) as image:size=image.size
                    return self.shelf.put(identity,data,source,size)
                await asyncio.to_thread(save)
                self.owner.on_change()
            except (OSError,ValueError,Image.DecompressionBombError):return
            except Exception:
                # The owner records FloodWait/cooldown; do not retry/probe here.
                return

    async def _loop(self) -> None:
        while not self.halt.is_set():
            job = await asyncio.to_thread(self._next)
            if job:
                await asyncio.to_thread(self._fill, job)
                await self._photo_cover(job[0]['identity'])
                continue
            identity=await asyncio.to_thread(self._next_photo)
            if identity:
                await self._photo_cover(identity)
                continue
            self.kick.clear()
            try:
                await asyncio.wait_for(self.kick.wait(), 5)
            except asyncio.TimeoutError:
                pass
