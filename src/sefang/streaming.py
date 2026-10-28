"""HTTP byte-range playback of Telegram videos.

Only one range per request is honoured; anything unusual is answered with 416
instead of a guessed body.  Bytes are pulled slice by slice only while the
client is still listening, and the playback slot is always given back.
"""
from __future__ import annotations

import asyncio
import re

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import Response, StreamingResponse

from .auth import COOKIE
from .tg.cache import SLICE
from .tg.link import TgProblem, explain

router = APIRouter()
_SPEC = re.compile(r"bytes=(\d*)-(\d*)")


class BadRange(ValueError):
    pass


def pick_range(header: str, size: int) -> tuple[int, int, int]:
    """(first, last, status) for a Range header against a body of `size` bytes."""
    if not header:
        return 0, size - 1, 200
    m = _SPEC.fullmatch(header.strip())
    if size <= 0 or not m or (not m.group(1) and not m.group(2)):
        raise BadRange(header)
    head, tail = m.group(1), m.group(2)
    if not head:
        suffix = int(tail)
        if suffix <= 0:
            raise BadRange(header)
        return max(0, size - suffix), size - 1, 206
    first = int(head)
    last = min(int(tail), size - 1) if tail else size - 1
    if first >= size or last < first:
        raise BadRange(header)
    return first, last, 206


class SlotStream(StreamingResponse):
    """Streaming body that closes its generator and frees the slot however the response ends."""

    def __init__(self, *args, on_finish, **kwargs):
        super().__init__(*args, **kwargs)
        self._on_finish = on_finish

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            try:
                await self.body_iterator.aclose()
            finally:
                self._on_finish()


def _refusal(error: BaseException) -> HTTPException:
    problem = explain(error)
    headers = {"Cache-Control": "no-store"}
    if problem.wait:
        headers["Retry-After"] = str(problem.wait)
    return HTTPException(410 if problem.gone else 503, str(problem), headers=headers)


@router.api_route("/api/videos/{channel_id}/{message_id}/stream", methods=["GET", "HEAD"])
async def play(channel_id: int, message_id: int, request: Request):
    control = request.app.state.playbacks
    token = request.cookies.get(COOKIE, "")
    person = control.guard(token)
    if channel_id not in request.app.state.config.channels or not 0 < message_id < 2 ** 53:
        raise HTTPException(404)
    if request.method == "HEAD" and request.query_params.get("playback"):
        control.check_lease(request.query_params["playback"], person, (channel_id, message_id))
    owner = request.app.state.telegram
    if owner is None:
        raise HTTPException(503, "媒体服务未连接")
    transfer = None
    gate_owned = False
    handed_over = False

    async def acquire_gate():
        nonlocal gate_owned
        await owner.media_gate.acquire()
        gate_owned = True

    def finish():
        nonlocal gate_owned
        if gate_owned:
            owner.media_gate.release()
            gate_owned = False
        if transfer is not None:
            control.release(transfer)

    try:
        if request.method != "HEAD":
            transfer = await control.claim(person, (channel_id, message_id), request.query_params.get("playback", ""))
        try:
            await control.wait(acquire_gate(), token, transfer, timeout=3)
        except asyncio.TimeoutError:
            raise HTTPException(429, "当前播放请求较多，请稍后重试", headers={"Retry-After": "3"}) from None
        row, message = await control.wait(owner.locate(channel_id, message_id), token, transfer)
        size = row["size"]
        tag = f'"tg-{channel_id}-{message_id}-{row["document_id"]}"'
        wanted = request.headers.get("range", "")
        if request.headers.get("if-range") not in (None, tag):
            wanted = ""
        try:
            first, last, status = pick_range(wanted, size)
        except BadRange:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes",
                                                      "Cache-Control": "no-store"})
        headers = {"Content-Length": str(max(0, last - first + 1)), "Accept-Ranges": "bytes", "ETag": tag,
                   "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
        if status == 206:
            headers["Content-Range"] = f"bytes {first}-{last}/{size}"
        if request.method == "HEAD" or size == 0:
            return Response(status_code=status, headers=headers, media_type=row["mime"])
        base = first - first % SLICE
        opening = await control.wait(owner.slice_at(row, message, base), token, transfer)

        async def pump():
            at, start, chunk = first, base, opening
            while at <= last:
                if await request.is_disconnected():
                    return
                control.guard(token, transfer)
                owner.allowed(channel_id)
                skip = at - start
                remaining = min(len(chunk) - skip, last - at + 1)
                if remaining <= 0:
                    raise TgProblem("媒体片段范围无效")
                while remaining:
                    n = await control.grant(token, transfer, remaining)
                    yield chunk[skip:skip+n]
                    at += n
                    skip += n
                    remaining -= n
                start += SLICE
                if at <= last:
                    chunk = await control.wait(owner.slice_at(row, message, start), token, transfer)

        class AuthorizedStream(SlotStream):
            async def __call__(self, scope, receive, send):
                # Also revoke blocked socket sends, not just owner/rate-limit waits.
                parent = asyncio.current_task()
                async def watch():
                    while True:
                        await asyncio.sleep(.25)
                        try:
                            control.guard(token, transfer)
                        except HTTPException:
                            parent.cancel()
                            return
                watcher = asyncio.create_task(watch())
                try:
                    await super().__call__(scope, receive, send)
                finally:
                    watcher.cancel()
                    await asyncio.gather(watcher, return_exceptions=True)

        response = AuthorizedStream(pump(), status_code=status, media_type=row["mime"], headers=headers, on_finish=finish)
        handed_over = True
        return response
    except HTTPException:
        raise
    except Exception as error:
        raise _refusal(error) from None
    finally:
        if not handed_over:
            finish()
