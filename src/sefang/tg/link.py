"""Thin adapter over Telethon for one already-authorised user session.

It never logs in: without a stored StringSession it simply reports "not
connected".  Media is read one slice at a time through Telethon's download
iterator (which also handles documents stored on other data centres).  If
Telegram answers with a CDN redirect, the encrypted slice is fetched from the
CDN node, decrypted with AES-256-CTR and checked against the published SHA-256
block hashes before any byte is handed out.
"""
from __future__ import annotations

import asyncio
import hashlib
from collections import OrderedDict

from Crypto.Cipher import AES
from telethon import TelegramClient, errors, events, functions, types, utils
from telethon.sessions import StringSession

from .cache import SLICE

CALL_TIMEOUT = 30
READ_TIMEOUT = 30


class TgProblem(Exception):
    """A Telegram failure in words safe to show; `gone` means the media will not come back."""

    def __init__(self, text: str, *, wait: int = 0, gone: bool = False):
        super().__init__(text)
        self.wait = wait
        self.gone = gone


EXPIRED_REFERENCE = (errors.FileReferenceExpiredError, errors.FilerefUpgradeNeededError)


def explain(error: BaseException) -> TgProblem:
    if isinstance(error, TgProblem):
        return error
    if isinstance(error, errors.FloodWaitError):
        return TgProblem(f"Telegram 限流中，约 {error.seconds} 秒后可重试", wait=int(error.seconds))
    if isinstance(error, (errors.ChannelPrivateError, errors.ChannelInvalidError, errors.ChatAdminRequiredError)):
        return TgProblem("频道不可访问或已失效", gone=True)
    if isinstance(error, (errors.AuthKeyUnregisteredError, errors.SessionRevokedError, errors.UserDeactivatedError)):
        return TgProblem("Telegram 会话已失效")
    if isinstance(error, (OSError, ConnectionError, asyncio.TimeoutError)):
        return TgProblem("连接 Telegram 失败，请稍后重试")
    return TgProblem("Telegram 请求未完成")


async def _bounded(awaitable, seconds=CALL_TIMEOUT):
    try:
        return await asyncio.wait_for(awaitable, seconds)
    except EXPIRED_REFERENCE:
        raise
    except Exception as error:
        raise explain(error) from None


def _input_channel(channel: dict):
    return types.InputChannel(int(channel["id"]), int(channel["access_hash"]))


def cdn_counter(iv: bytes, block_offset: int) -> int:
    """Initial AES-CTR counter for a CDN block starting at `block_offset`."""
    return int.from_bytes(iv[:12] + (block_offset // 16).to_bytes(4, "big"), "big")


class TgLink:
    def __init__(self, account: dict, on_update):
        self.account = account
        self.on_update = on_update
        self.client: TelegramClient | None = None
        self._redirects: OrderedDict[int, object] = OrderedDict()
        self._edge: dict[int, object] = {}

    async def connect(self) -> bool:
        if self.client is not None and self.client.is_connected():
            return bool(await _bounded(self.client.is_user_authorized()))
        api_id, api_hash = self.account.get("api_id"), self.account.get("api_hash")
        saved = self.account.get("session") or ""
        if not api_id or not api_hash or not saved:
            return False
        if self.client is not None:
            await self.client.disconnect()
        client = TelegramClient(StringSession(saved), int(api_id), str(api_hash), request_retries=1,
                                connection_retries=3, retry_delay=1, flood_sleep_threshold=0,
                                auto_reconnect=True, receive_updates=True)
        client.add_event_handler(self._changed, events.NewMessage())
        client.add_event_handler(self._changed, events.MessageEdited())
        client.add_event_handler(self._removed, events.MessageDeleted())
        self.client = client
        await _bounded(client.connect())
        ok = bool(await _bounded(client.is_user_authorized()))
        if ok:
            await _bounded(client.get_me())
        return ok

    async def close(self) -> None:
        if self.client is not None:
            await self.client.disconnect()
            self.client = None
        for edge in self._edge.values():
            await edge.disconnect()
        self._edge.clear()
        self._redirects.clear()

    async def history(self, channel: dict, *, before: int = 0, after: int | None = None):
        if after is not None:
            query = dict(limit=100, min_id=after, reverse=True)
        else:
            query = dict(limit=100, offset_id=before)
        return await _bounded(self.client.get_messages(_input_channel(channel), **query))

    async def message(self, channel: dict, message_id: int):
        return await _bounded(self.client.get_messages(_input_channel(channel), ids=message_id))

    async def thumbnail(self, message) -> bytes | None:
        return await _bounded(self.client.download_media(message, file=bytes, thumb=-1))

    async def photo(self, message, limit: int) -> bytes | None:
        """Bound actual photo bytes before IO; never download a document/video."""
        photo=getattr(message,'photo',None)
        if not isinstance(photo,types.Photo):return None
        sizes=[]
        for s in photo.sizes:
            n=max(s.sizes) if isinstance(s,types.PhotoSizeProgressive) and s.sizes else getattr(s,'size',0)
            if isinstance(s,(types.PhotoSize,types.PhotoSizeProgressive)) and 0<n<=limit:
                sizes.append((s.w*s.h,n,s))
        if not sizes:return None
        _,expected,size=max(sizes,key=lambda x:x[0])
        location=types.InputPhotoFileLocation(photo.id,photo.access_hash,photo.file_reference,size.type)
        async def download():
            chunks=[];total=0
            stream=self.client.iter_download(location,request_size=SLICE,chunk_size=SLICE,
                limit=(expected+SLICE-1)//SLICE,file_size=expected,dc_id=photo.dc_id)
            try:
                async for chunk in stream:
                    total+=len(chunk)
                    if total>limit or total>expected:return None
                    chunks.append(bytes(chunk))
            finally:await stream.close()
            return b''.join(chunks) if total==expected else None
        return await _bounded(download())

    async def read(self, message, offset: int, count: int) -> bytes:
        """`count` bytes starting at `offset` (a SLICE boundary) of the message's document."""
        doc = message.document
        redirect = self._redirects.get(doc.id)
        if redirect is None:
            pieces = self.client.iter_download(doc, offset=offset, request_size=SLICE, chunk_size=SLICE, limit=1)
            try:
                chunk = await asyncio.wait_for(pieces.__anext__(), READ_TIMEOUT)
                return bytes(chunk[:count])
            except StopAsyncIteration:
                return b""
            except EXPIRED_REFERENCE:
                raise
            except Exception as error:
                redirect = getattr(error, "cdn_redirect", None)
                if not isinstance(redirect, types.upload.FileCdnRedirect):
                    raise explain(error) from None
                self._redirects[doc.id] = redirect
                while len(self._redirects) > 128:
                    self._redirects.popitem(last=False)
            finally:
                await pieces.close()
        try:
            return await self._read_edge(redirect, offset, count)
        except EXPIRED_REFERENCE:
            raise
        except Exception as error:
            self._redirects.pop(doc.id, None)
            raise explain(error) from None

    async def _edge_client(self, redirect):
        dc = redirect.dc_id
        if dc not in self._edge:
            if len(self._edge) >= 8:
                _, old = self._edge.popitem()
                await old.disconnect()
            self._edge[dc] = await _bounded(self.client._get_cdn_client(redirect))
        return self._edge[dc]

    async def _read_edge(self, redirect, offset: int, count: int) -> bytes:
        edge = await self._edge_client(redirect)
        want_end = offset + count
        out = bytearray()
        position = offset
        blocks = list(redirect.file_hashes)
        while position < want_end:
            block = next((b for b in blocks if b.offset <= position < b.offset + b.limit), None)
            if block is None:
                ask_hashes = functions.upload.GetCdnFileHashesRequest(redirect.file_token, position)
                blocks = list(await _bounded(self.client(ask_hashes)))
                block = next((b for b in blocks if b.offset <= position < b.offset + b.limit), None)
            if block is None or not 0 < block.limit <= 1024 * 1024 or block.offset % 16:
                raise TgProblem("Telegram CDN 返回了无效的校验块")
            ask = functions.upload.GetCdnFileRequest(redirect.file_token, block.offset, block.limit)
            reply = await _bounded(edge(ask), READ_TIMEOUT)
            if isinstance(reply, types.upload.CdnFileReuploadNeeded):
                again = functions.upload.ReuploadCdnFileRequest(redirect.file_token, reply.request_token)
                await _bounded(self.client(again))
                reply = await _bounded(edge(ask), READ_TIMEOUT)
            if not isinstance(reply, types.upload.CdnFile):
                raise TgProblem("Telegram CDN 未返回数据")
            cipher = AES.new(redirect.encryption_key, AES.MODE_CTR, nonce=b"",
                             initial_value=cdn_counter(redirect.encryption_iv, block.offset))
            plain = cipher.decrypt(reply.bytes)
            if hashlib.sha256(plain).digest() != block.hash:
                raise TgProblem("Telegram CDN 数据校验失败")
            start = position - block.offset
            take = min(len(plain) - start, want_end - position)
            if take <= 0:
                break
            out += plain[start:start + take]
            position += take
        return bytes(out)

    async def _changed(self, event) -> None:
        peer = getattr(event.message, "peer_id", None)
        channel_id = getattr(peer, "channel_id", None)
        if channel_id is not None:
            await self.on_update(int(channel_id), event.message, None)

    async def _removed(self, event) -> None:
        chat = getattr(event, "chat_id", None)
        if chat is None:
            return
        real_id, _ = utils.resolve_id(int(chat))
        await self.on_update(int(real_id), None, list(event.deleted_ids))
