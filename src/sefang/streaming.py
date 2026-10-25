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
    if channel_id not in request.app.state.config.channels or not 0 < message_id < 2 ** 53:
        raise HTTPException(404)
    owner = request.app.state.telegram
    if owner is None:
        raise HTTPException(503, "媒体服务未连接")
    try:
        await asyncio.wait_for(owner.media_gate.acquire(), 3)
    except asyncio.TimeoutError:
        raise HTTPException(429, "当前播放请求较多，请稍后重试", headers={"Retry-After": "3"}) from None
    handed_over = False
    try:
        row, message = await owner.locate(channel_id, message_id)
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
        opening = await owner.slice_at(row, message, base)

        async def pump():
            at, start, chunk = first, base, opening
            while at <= last:
                if await request.is_disconnected():
                    return
                owner.allowed(channel_id)
                skip = at - start
                n = min(len(chunk) - skip, last - at + 1)
                if n <= 0:
                    raise TgProblem("媒体片段范围无效")
                yield chunk[skip:skip + n]
                at += n
                start += SLICE
                if at <= last:
                    chunk = await owner.slice_at(row, message, start)

        response = SlotStream(pump(), status_code=status, media_type=row["mime"], headers=headers,
                              on_finish=owner.media_gate.release)
        handed_over = True
        return response
    except HTTPException:
        raise
    except Exception as error:
        raise _refusal(error) from None
    finally:
        if not handed_over:
            owner.media_gate.release()
