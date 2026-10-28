"""Fail-closed HTTP boundary and process-local account-wide streaming controls.

The existing Telegram owner is single-process; these controls deliberately share
that lifetime. A playback id is NOT a credential: the current session is required,
and each active server-issued id is one playback window. A window permits
at most two bounded responses; neither cancels the other.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hmac
import re
import secrets
import time
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from .auth import COOKIE, Principal, Input, LIFETIME
from pydantic import StrictInt, Field

router = APIRouter()
WRITES = {
    "POST": [re.compile(p + r"\Z") for p in (
        r"/api/history/context", r"/api/history/progress", r"/api/history/clear",
        r"/api/history/[0-9a-f]{32}/delete",
        r"/api/auth/login", r"/api/auth/logout", r"/api/admin/accounts",
        r"/api/admin/accounts/[0-9]+/password", r"/api/playbacks",
        r"/api/playbacks/[A-Za-z0-9_-]{32}/close")],
    "PATCH": [re.compile(r"/api/admin/accounts/[0-9]+\Z")],
}
SECURITY = {"X-Robots-Tag": "noindex, nofollow, noarchive", "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY"}


class Boundary:
    def __init__(self, app, store, csp):
        self.app, self.store, self.csp = app, store, csp

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope, receive)
        path, method = request.url.path, request.method
        public = path in ("/login", "/healthz") or path.startswith("/assets/")
        login = path == "/api/auth/login" and method == "POST"
        person = None

        async def wrapped(message):
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                for key, value in {**SECURITY, "Content-Security-Policy": self.csp}.items():
                    headers[key.lower().encode()] = value.encode()
                if not path.startswith("/assets/"):
                    headers[b"cache-control"] = b"private, no-store, max-age=0"
                    headers[b"pragma"] = b"no-cache"
                    headers[b"vary"] = b"Cookie"
                message["headers"] = list(headers.items())
            await send(message)

        async def refuse(code, text, headers=None):
            await JSONResponse({"detail": text}, status_code=code, headers=headers)(scope, receive, wrapped)

        if method not in ("GET", "HEAD") and not any(p.fullmatch(path) for p in WRITES.get(method, [])):
            return await refuse(405, "不支持此操作", {"Allow": "GET, HEAD"})
        if not public and not login:
            person = self.store.authenticate(request.cookies.get(COOKIE, ""))
            if not person:
                if method in ("GET", "HEAD") and not path.startswith("/api/"):
                    target = path + (("?" + request.url.query) if request.url.query else "")
                    return await RedirectResponse("/login?next=" + quote(target, safe=""), status_code=303)(scope, receive, wrapped)
                return await refuse(401, "请先登录")
            scope.setdefault("state", {})["principal"] = person
        if method not in ("GET", "HEAD"):
            # Compare the original Host, not forwarded headers. Production is HTTPS behind Caddy.
            try:
                origin = urlsplit(request.headers.get("origin", ""))
            except ValueError:
                return await refuse(403, "请求来源无效")
            if origin.scheme != "https" or origin.netloc != request.headers.get("host", "") or origin.path or origin.query or origin.fragment:
                return await refuse(403, "请求来源无效")
            if not login and (not person or not hmac.compare_digest(request.headers.get("x-csrf-token", "").encode(), person.csrf.encode())):
                return await refuse(403, "请求验证失败，请刷新重试")
            if request.headers.get("content-type", "").split(";")[0] != "application/json":
                return await refuse(415, "需要 JSON 请求")
            try:
                length = int(request.headers.get("content-length", "-1"))
            except ValueError:
                length = -1
            if not 0 <= length <= 8192:
                return await refuse(413, "请求体无效或过大")
        await self.app(scope, receive, wrapped)


@dataclass
class Transfer:
    person: Principal
    task: asyncio.Task
    key: str
    leased: bool
    done: asyncio.Event = field(default_factory=asyncio.Event)


class PlaybackControl:
    def __init__(self, store):
        self.store = store
        self.leases = {}  # id -> (account id, session digest, last touched, allowed media)
        self.active: dict[str, list[Transfer]] = {}
        self.lock = asyncio.Lock()
        self.buckets = {}

    def create(self, person, media):
        now = time.monotonic()
        self.leases = {k: v for k, v in self.leases.items() if k in self.active or v[2] > now-LIFETIME}
        if sum(v[1] == person.session for v in self.leases.values()) >= 32:
            raise HTTPException(429, "播放窗口过多，请关闭不用的窗口后重试")
        key = secrets.token_urlsafe(24)
        self.leases[key] = (person.id, person.session, now, frozenset(media))
        return key

    def check_lease(self, key, person, media=None):
        lease = self.leases.get(key)
        if not lease or lease[:2] != (person.id, person.session):
            raise HTTPException(403, "播放许可失效，请重新打开视频")
        if media is not None and media not in lease[3]:
            raise HTTPException(403, "播放许可不属于此视频")
        self.leases[key] = (*lease[:2], time.monotonic(), lease[3])

    def windows(self, person):
        # Insertion order survives until the LAST response of a window releases.
        return [key for key, responses in self.active.items() if responses[0].person.id == person.id]

    async def claim(self, person, media, key=""):
        async with self.lock:
            leased = bool(key)
            if key:
                self.check_lease(key, person, media)
            else:
                # Legacy URLs have no trusted window association: each is independent.
                key = "direct-" + secrets.token_urlsafe(24)
            windows = self.windows(person)
            if key in self.active:
                if key not in windows[:person.max_playbacks]:
                    raise HTTPException(429, "同时播放上限已调整")
                # No unbounded wait queue and no destructive same-lease replacement.
                if len(self.active[key]) >= 2:
                    raise HTTPException(429, "本播放窗口的媒体请求较多，请稍后重试", headers={"Retry-After": "1"})
            elif len(windows) >= person.max_playbacks:
                raise HTTPException(429, "已达到此账号的同时播放上限，请先关闭其他播放", headers={"Retry-After": "1"})
            transfer = Transfer(person, asyncio.current_task(), key, leased)
            self.active.setdefault(key, []).append(transfer)
            return transfer

    def release(self, transfer):
        responses = self.active.get(transfer.key, [])
        if transfer in responses:
            responses.remove(transfer)
            if not responses:
                del self.active[transfer.key]
        transfer.done.set()

    def close(self, key, person):
        self.check_lease(key, person)
        self.leases.pop(key, None)
        for transfer in tuple(self.active.get(key, ())):
            transfer.task.cancel()

    def guard(self, token, transfer=None):
        person = self.store.authenticate(token)
        if not person:
            raise HTTPException(401, "登录已失效")
        if transfer:
            if transfer.leased:
                self.check_lease(transfer.key, person)
            # Lowered limits retain the oldest active WINDOWS, including all their
            # bounded responses. Finishing one Range must not evict its sibling.
            if transfer.key not in self.windows(person)[:person.max_playbacks]:
                raise HTTPException(429, "同时播放上限已调整")
        return person

    async def wait(self, awaitable, token, transfer=None, timeout=60):
        """Bound every owner/gate wait with a session check, without speculative extra reads."""
        task = asyncio.ensure_future(awaitable)
        deadline = time.monotonic() + timeout
        try:
            while True:
                self.guard(token, transfer)
                done, _ = await asyncio.wait((task,), timeout=min(.25, max(0, deadline-time.monotonic())))
                if done:
                    self.guard(token, transfer)
                    return task.result()
                if time.monotonic() >= deadline:
                    raise asyncio.TimeoutError
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def grant(self, token, transfer, wanted):
        bucket = self.buckets.setdefault(transfer.person.id, Bucket())
        # asyncio.Lock is FIFO: each response takes at most one 32KiB turn.
        async with bucket.lock:
            while True:
                person = self.guard(token, transfer)
                now = time.monotonic()
                rate = person.rate
                if rate is None:
                    bucket.rate, bucket.at, bucket.tokens = None, now, 0
                    return min(32768, wanted)
                cap = max(1, min(65536, rate // 10))
                if bucket.rate != rate:
                    bucket.tokens = min(bucket.tokens, cap) if bucket.rate is not None else cap
                    bucket.rate = rate
                bucket.tokens = min(cap, bucket.tokens + (now-bucket.at)*rate)
                bucket.at = now
                amount = min(32768, cap, wanted)
                if bucket.tokens >= amount:
                    bucket.tokens -= amount
                    return amount
                await asyncio.sleep(min(.25, (amount-bucket.tokens)/rate))


class Bucket:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.tokens, self.at, self.rate = 0, time.monotonic(), None


class PlaybackInput(Input):
    channel_id: StrictInt = Field(gt=0, lt=2**53)
    message_id: StrictInt = Field(gt=0, lt=2**53)


@router.post("/api/playbacks")
async def begin(data: PlaybackInput, request: Request):
    if data.channel_id not in request.app.state.config.channels:
        raise HTTPException(404)
    snapshot = await asyncio.to_thread(request.app.state.repository.snapshot)
    group = snapshot.by_message.get((data.channel_id, data.message_id))
    if group is None:
        raise HTTPException(404)
    # Include the original repository's aliases, not just the representative DTO parts.
    # Otherwise opening a retained legacy/alias URL could reject its own stream.
    media = {key for key in group.keys if key[0] in request.app.state.config.channels}
    return {"id": request.app.state.playbacks.create(request.state.principal, media)}


@router.post("/api/playbacks/{key}/close")
async def close(key: str, request: Request):
    request.app.state.playbacks.close(key, request.state.principal)
    return {"ok": True}
