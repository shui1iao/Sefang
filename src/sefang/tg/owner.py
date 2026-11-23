"""The single process that owns the Telegram session for this site.

Responsibilities: keep the connection alive, index the allow-listed channel
(catch-up after downtime plus a one-off backwards walk of the history), apply
live new/edit/delete updates, and serve media slices on demand.
"""
from __future__ import annotations

import asyncio
import json
import logging
import struct
from pathlib import Path
from time import monotonic

from telethon.sessions import StringSession

from .cache import BUDGET, SLICE, SliceCache
from .index import ChannelIndex, video_from_message, album_context_from_message
from .link import EXPIRED_REFERENCE, TgLink, TgProblem, TgSessionRejected, explain
from .media_gate import MediaGate
from .. import codes

PAGE = 100
SYNC_INTERVAL = 60
RETRY_DELAYS = (60, 120, 240, 300)
READY_MAX_AGE = 3 * SYNC_INTERVAL
log = logging.getLogger(__name__)


def read_account(path: Path) -> tuple[dict, bool]:
    """(account dict, unreadable flag).  Never echoes the file contents anywhere."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("channels", []), list):
            raise ValueError
        return data, False
    except FileNotFoundError:
        return {"channels": []}, False
    except (OSError, ValueError):
        return {"channels": []}, True


class ChannelOwner:
    def __init__(self, config, *, link_factory=TgLink):
        self.config = config
        self.account, broken = read_account(Path(config.secrets_root) / "telegram" / "account.json")
        self.index = ChannelIndex(config.db)
        self.cache = SliceCache(Path(config.candidate_root) / "telegram-chunks", BUDGET)
        self.link = link_factory(self.account, self.on_update)
        self.state = "error" if broken else ("pending_login" if self.account.get("api_id") else "unconfigured")
        self.problem = "账号配置不可读" if broken else ""
        self._broken_account = broken
        self._rejected_session = False
        if isinstance(self.link, TgLink) and self.account.get("session"):
            # A malformed/empty key is not a session we should connect with.
            saved = self.account["session"]
            try:
                self._rejected_session = not isinstance(saved, str) or StringSession(saved).auth_key is None
            except (ValueError, struct.error):
                self._rejected_session = True
        self.failures = 0
        self.not_before = 0.0
        self._last_sync: float | None = None
        self._reported_ready: bool | None = None
        self.media_gate = MediaGate()
        self.read_gate = asyncio.Lock()
        self.on_change = lambda: None
        self._loop_task: asyncio.Task | None = None

    # ---- allow list
    def channels(self) -> list[dict]:
        return list(self.account.get("channels") or [])

    def allowed(self, channel_id: int) -> dict:
        for channel in self.channels():
            if channel["id"] == channel_id:
                return channel
        raise TgProblem("频道不在允许列表中", gone=True)

    # ---- lifecycle
    async def start(self) -> None:
        if self._loop_task is None:
            self._loop_task = asyncio.create_task(self._keepalive())

    async def stop(self) -> None:
        if self._loop_task is not None:
            self._loop_task.cancel()
            await asyncio.gather(self._loop_task, return_exceptions=True)
            self._loop_task = None
        self._last_sync = None
        if self.state == "connected":
            self.state = "paused"
        if self._reported_ready is not None:
            self._publish_health(False)
        await self.link.close()

    def _connection_block(self) -> str | None:
        if self._broken_account:
            return "error"
        if self.account.get("paused"):
            return "paused"
        if not self.account.get("api_id") or not self.account.get("api_hash"):
            return "unconfigured"
        if not self.account.get("session") or self._rejected_session:
            return "pending_login"
        return None

    def _publish_health(self, ready: bool) -> None:
        if self._reported_ready != ready:
            self._reported_ready = ready
            # Warning also for recovery: the service is run with warning-level logging.
            log.warning("telegram_business_health=%s", "ready" if ready else "not_ready")

    def business_ready(self) -> bool:
        if isinstance(self.link, TgLink):
            client = self.link.client
            if client is None or not client.is_connected():
                self._last_sync = None
        ready = (self._loop_task is not None and not self._loop_task.done()
                 and self._connection_block() is None and self.state == "connected"
                 and self._last_sync is not None
                 and monotonic() - self._last_sync < READY_MAX_AGE)
        self._publish_health(ready)
        return ready

    def _failed(self, error: BaseException) -> TgProblem:
        problem = explain(error)
        self.failures += 1
        self.state, self.problem = "error", str(problem)
        delay = RETRY_DELAYS[min(self.failures, len(RETRY_DELAYS)) - 1]
        self.not_before = max(self.not_before, monotonic() + max(delay, problem.wait))
        self._last_sync = None
        self._publish_health(False)
        return problem

    async def _sleep(self, delay: float) -> None:
        await asyncio.sleep(delay)

    async def _keepalive(self) -> None:
        reset_link = False
        while True:
            self.business_ready()
            blocked = self._connection_block()
            if blocked is not None:
                self.state = blocked
                self._last_sync = None
                await self._sleep(SYNC_INTERVAL)
                continue
            remaining = self.not_before - monotonic()
            if remaining > 0:
                await self._sleep(remaining)
                continue
            try:
                if reset_link:
                    await self.link.close()
                    reset_link = False
                if self.not_before > monotonic():
                    continue
                if not await self.link.connect():
                    # A boolean does not prove the saved session has been revoked.
                    raise TgProblem("Telegram 会话暂未确认")
            except TgSessionRejected as problem:
                self._rejected_session = True
                self.state, self.problem = "pending_login", str(problem)
                self._last_sync = None
                self._publish_health(False)
                try:
                    await self.link.close()
                except Exception as error:
                    self._failed(error)
                continue
            except Exception as error:
                # A timed-out initialization can leave a half-connected client.
                reset_link = True
                self._failed(error)
                continue
            if self.not_before > monotonic():
                continue  # a concurrent media request may have reported a wait
            self.state, self.problem = "connected", ""
            # One owner runs one catch-up at a time; cancellation marks its channel paused.
            await self._sync_all()
            if self.not_before <= monotonic():
                await self._sleep(SYNC_INTERVAL)

    # ---- indexing
    def _keep(self, channel: dict, messages, **marks) -> None:
        rows, contexts = [], []
        for message in messages:
            row = video_from_message(channel['id'], message, protected=bool(channel.get('protected')))
            if row is not None:
                rows.append(row)
            else:
                contexts.append(album_context_from_message(channel['id'], message))
        self.index.store(channel["id"], rows, contexts=contexts, scanned=len(messages), **marks)
        self.on_change()

    async def _sync_all(self) -> None:
        current = 0
        failures = self.failures
        try:
            for channel in self.channels():
                current = channel["id"]
                self.index.ensure_channel(current, channel["title"])
                saved = self.index.channel_row(current)
                newest = saved["high_water"]
                while newest:
                    if self.failures != failures:
                        return  # do not issue new RPCs after a concurrent FloodWait
                    batch = await self.link.history(channel, after=newest)
                    if not batch:
                        break
                    newest = max(m.id for m in batch)
                    self._keep(channel, batch, high_water=newest)
                    if len(batch) < PAGE:
                        break
                    await asyncio.sleep(0)
                if not saved["history_done"]:
                    cursor = saved["history_cursor"]
                    while True:
                        if self.failures != failures:
                            return
                        batch = await self.link.history(channel, before=cursor)
                        finished = len(batch) < PAGE
                        if batch:
                            cursor = min(m.id for m in batch)
                        self._keep(channel, batch, cursor=cursor, done=finished,
                                   high_water=max((m.id for m in batch), default=0))
                        if finished:
                            break
                        await asyncio.sleep(0)
                self.index.set_state(current, "ready")
            if self.failures == failures:
                self.failures = 0
                self.not_before = 0.0
                self._last_sync = monotonic()
                self.business_ready()
        except asyncio.CancelledError:
            if current:
                self.index.set_state(current, "paused")
            raise
        except Exception as error:
            problem = self._failed(error)
            if current:
                try:
                    self.index.set_state(current, "error", str(problem))
                except Exception:
                    # The index itself may be temporarily unavailable. Keep retrying.
                    pass

    async def on_update(self, channel_id: int, message, deleted_ids) -> None:
        try:
            channel = self.allowed(channel_id)
        except TgProblem:
            return
        if deleted_ids:
            for mid in deleted_ids:
                self.index.mark_gone(channel_id, mid)
            self.on_change()
            return
        if message is None:
            return
        row = video_from_message(channel_id, message, protected=bool(channel.get("protected")))
        if row is None:
            self.index.store(channel_id, [], contexts=[album_context_from_message(channel_id, message)])
            self.on_change()
            return
        # live events never move the recovery high-water mark; the next catch-up fills gaps
        self.index.store(channel_id, [row])
        self.on_change()

    # ---- media
    def _media_connected(self) -> bool:
        return self.state == "connected" and monotonic() >= self.not_before

    async def locate(self, channel_id: int, message_id: int):
        channel = self.allowed(channel_id)
        if not self._media_connected():
            raise TgProblem("Telegram 尚未连接")
        try:
            message = await self.link.message(channel, message_id)
        except TgProblem as problem:
            if problem.wait:
                self._failed(problem)
            if problem.gone:
                self.index.mark_gone(channel_id, message_id)
            raise
        row = video_from_message(channel_id, message, protected=bool(channel.get("protected"))) if message else None
        if row is None:
            if message is not None:
                self.index.store(channel_id, [], contexts=[album_context_from_message(channel_id, message)])
            else:
                self.index.mark_gone(channel_id, message_id)
            self.on_change()
            raise TgProblem("原消息已删除或视频不可用", gone=True)
        if row["protected"]:
            self.cache.forget(SliceCache.media_key(channel_id, message_id, row["document_id"]))
        if self.index.store(channel_id, [row]):
            self.on_change()
        return row, message

    def _slice_protection(self, row: dict) -> bool:
        cid, mid = row["channel_id"], row["message_id"]
        self.allowed(cid)
        if not self._media_connected():
            raise TgProblem("Telegram 连接已停止")
        now = self.index.video(cid, mid)
        if not now or not now["available"] or now["document_id"] != row["document_id"]:
            raise TgProblem("视频已删除或被替换，请重新打开", gone=True)
        return bool(row["protected"] or now["protected"])

    async def slice_at(self, row: dict, message, offset: int) -> bytes:
        cid, mid = row["channel_id"], row["message_id"]
        media = SliceCache.media_key(cid, mid, row["document_id"])
        size = min(SLICE, row["size"] - offset)
        protected = bool(row["protected"])
        if self.read_gate.locked():
            # A trusted disk hit has no upstream work. Keep the miss path
            # serialized and recheck the index after waiting for it.
            protected = self._slice_protection(row)
            if not protected:
                hit = self.cache.load(media, offset, size)
                if hit is not None:
                    return hit
        async with self.read_gate:
            protected = self._slice_protection(row) or protected
            if protected:
                self.cache.forget(media)
            else:
                hit = self.cache.load(media, offset, size)
                if hit is not None:
                    return hit
            for attempt in (0, 1):
                try:
                    data = await asyncio.wait_for(self.link.read(message, offset, size), 45)
                    break
                except EXPIRED_REFERENCE:
                    if attempt:
                        raise TgProblem("媒体引用已过期，请重新打开") from None
                    fresh, message = await self.locate(cid, mid)
                    if fresh["document_id"] != row["document_id"] or fresh["size"] != row["size"]:
                        raise TgProblem("视频已被替换，请重新打开", gone=True) from None
                    protected = protected or bool(fresh["protected"])
                except TgProblem as problem:
                    if problem.wait:
                        self._failed(problem)
                    raise
            if len(data) != size:
                raise TgProblem("Telegram 返回的片段不完整")
            if not protected:
                self.cache.save(media, offset, data)
            return data

    async def cover_photo(self, candidate: dict, limit: int):
        """Recheck both source messages using this owner's original client, then read only photo."""
        cid=candidate['channel_id'];channel=self.allowed(cid)
        if not self._media_connected():return None
        async with self.media_gate.artwork():
            if not self._media_connected():return None
            try:
                photo=await self.link.message(channel,candidate['message_id'])
                if not self._media_connected():return None
                video=await self.link.message(channel,candidate['video_id'])
                if photo is None:self.index.mark_gone(cid,candidate['message_id'])
                else:
                    replacement=video_from_message(cid,photo,protected=bool(channel.get('protected')))
                    if replacement:self.index.store(cid,[replacement])
                    else:self.index.store(cid,[],contexts=[album_context_from_message(cid,photo)])
                row=video_from_message(cid,video,protected=bool(channel.get('protected'))) if video else None
                if row:self.index.store(cid,[row])
                elif video:self.index.store(cid,[],contexts=[album_context_from_message(cid,video)])
                else:self.index.mark_gone(cid,candidate['video_id'])
                self.on_change()
                # Index title can be a caption fallback when the document had no filename.
                # Only the real document attribute can authorize a cover binding.
                filename=next((a.file_name for a in getattr(getattr(video,'document',None),'attributes',[]) if getattr(a,'file_name',None) is not None),'')
                found=codes.numbers_in(filename,as_filename=True)
                if len(found)!=1 or codes.identity(found[0])!=candidate['identity']:return None
                if candidate not in self.index.photo_candidates(candidate['identity'],[cid]):return None
                if not self._media_connected():return None
                data=await self.link.photo(photo,limit)
                if not data or len(data)>limit or candidate not in self.index.photo_candidates(candidate['identity'],[cid]):return None
                source=json.dumps({'kind':'channel_photo','channel_id':cid,'photo_message_id':candidate['message_id'],
                    'video_message_id':candidate['video_id'],'grouped_id':candidate['grouped_id'],
                    'identity':candidate['identity'],'photo_id':candidate['photo_id']},sort_keys=True)
                return data,source
            except Exception as error:
                problem=explain(error)
                if problem.wait:self._failed(problem)
                raise problem from None

    async def thumbnail(self, channel_id: int, message_id: int) -> bytes | None:
        async with self.media_gate.artwork():
            _, message = await self.locate(channel_id, message_id)
            if not self._media_connected():
                return None
            try:
                data = await self.link.thumbnail(message)
            except TgProblem as problem:
                if problem.wait:
                    self._failed(problem)
                raise
            if not data or len(data) > 2 * 1048576:
                return None
            return bytes(data)
