"""The single process that owns the Telegram session for this site.

Responsibilities: keep the connection alive, index the allow-listed channel
(catch-up after downtime plus a one-off backwards walk of the history), apply
live new/edit/delete updates, and serve media slices on demand.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from .cache import BUDGET, SLICE, SliceCache
from .index import ChannelIndex, video_from_message, album_context_from_message
from .link import EXPIRED_REFERENCE, TgLink, TgProblem, explain
from .. import codes

PAGE = 100
MAX_FAILURES = 3


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
        self.failures = 0
        self.not_before = 0.0
        self.media_gate = asyncio.Semaphore(2)
        self.read_gate = asyncio.Lock()
        self.kick = asyncio.Event()
        self.on_change = lambda: None
        self._loop_task: asyncio.Task | None = None
        self._sync_task: asyncio.Task | None = None

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
        for task in (self._sync_task, self._loop_task):
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self._sync_task = self._loop_task = None
        await self.link.close()

    def _failed(self, error: BaseException) -> TgProblem:
        problem = explain(error)
        self.failures += 1
        self.state, self.problem = "error", str(problem)
        self.not_before = max(self.not_before, time.time() + max(60, problem.wait))
        return problem

    async def _keepalive(self) -> None:
        while True:
            try:
                ready = (self.account.get("session") and not self.account.get("paused")
                         and self.failures < MAX_FAILURES and time.time() >= self.not_before)
                if ready:
                    if await self.link.connect():
                        self.state, self.problem = "connected", ""
                        if self._sync_task is None or self._sync_task.done():
                            self._sync_task = asyncio.create_task(self._sync_all())
                    else:
                        self.state = "pending_login"
                self.kick.clear()
                try:
                    await asyncio.wait_for(self.kick.wait(), 60)
                except asyncio.TimeoutError:
                    pass
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self._failed(error)
                await asyncio.sleep(5)
                try:
                    await asyncio.wait_for(self.kick.wait(), max(60, self.not_before - time.time()))
                except asyncio.TimeoutError:
                    pass

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
        try:
            for channel in self.channels():
                current = channel["id"]
                self.index.ensure_channel(current, channel["title"])
                saved = self.index.channel_row(current)
                newest = saved["high_water"]
                while newest:
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
            self.failures = 0
        except asyncio.CancelledError:
            if current:
                self.index.set_state(current, "paused")
            raise
        except Exception as error:
            problem = self._failed(error)
            if current:
                self.index.set_state(current, "error", str(problem))

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
    async def locate(self, channel_id: int, message_id: int):
        channel = self.allowed(channel_id)
        if self.state != "connected":
            raise TgProblem("Telegram 尚未连接")
        try:
            message = await self.link.message(channel, message_id)
        except TgProblem as problem:
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

    async def slice_at(self, row: dict, message, offset: int) -> bytes:
        cid, mid = row["channel_id"], row["message_id"]
        self.allowed(cid)
        if self.state != "connected":
            raise TgProblem("Telegram 连接已停止")
        now = self.index.video(cid, mid)
        if not now or not now["available"] or now["document_id"] != row["document_id"]:
            raise TgProblem("视频已删除或被替换，请重新打开", gone=True)
        protected = bool(row["protected"] or now["protected"])
        media = SliceCache.media_key(cid, mid, row["document_id"])
        size = min(SLICE, row["size"] - offset)
        async with self.read_gate:
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
        if self.state!='connected' or time.time()<self.not_before:return None
        async with self.media_gate:
            try:
                photo=await self.link.message(channel,candidate['message_id'])
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
        async with self.media_gate:
            _, message = await self.locate(channel_id, message_id)
            data = await self.link.thumbnail(message)
            if not data or len(data) > 2 * 1048576:
                return None
            return bytes(data)
