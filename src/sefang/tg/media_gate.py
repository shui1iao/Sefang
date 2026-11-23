"""Bound the shared Telegram media lane without making playback wait behind artwork."""
from __future__ import annotations

import asyncio
from collections import deque
from contextlib import asynccontextmanager


class MediaGate:
    """Two total slots; artwork uses at most one, with queued playback first."""

    def __init__(self) -> None:
        self._value = 2
        self._playback: deque[asyncio.Future[None]] = deque()
        self._artwork = asyncio.Lock()
        self._artwork_ready = asyncio.Event()

    def _wake(self) -> None:
        if self._value == 0:
            return
        if self._playback:
            head = self._playback[0]
            if not head.done():
                head.set_result(None)
        else:
            self._artwork_ready.set()

    async def acquire(self) -> None:
        if self._value and not self._playback:
            self._value -= 1
            return
        pending = asyncio.get_running_loop().create_future()
        self._playback.append(pending)
        try:
            # Keep the head queued until it actually acquires. Cancelling a
            # notified waiter leaves its slot untouched for the next waiter.
            await pending
            self._value -= 1
        finally:
            self._playback.remove(pending)
            self._wake()

    def release(self) -> None:
        if self._value == 2:
            raise RuntimeError("media slot was not acquired")
        self._value += 1
        self._wake()

    @asynccontextmanager
    async def artwork(self):
        async with self._artwork:
            while not self._value or self._playback:
                self._artwork_ready.clear()
                await self._artwork_ready.wait()
            self._value -= 1
            try:
                yield
            finally:
                self.release()
