"""Bounded on-disk cache of fixed-size media slices.

Slices are 512 KiB aligned windows of a Telegram document.  The directory is
shared by everything that ever cached there, so the budget counts every
``*.bin`` file regardless of who wrote it, and the least recently used ones are
removed first.  A cross-process file lock guards bookkeeping.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from filelock import FileLock

from .index import lock_down_dir

SLICE = 512 * 1024
BUDGET = 512 * 1024 * 1024


def _charge(stat: os.stat_result) -> int:
    return max(SLICE, stat.st_size, getattr(stat, "st_blocks", 0) * 512)


class SliceCache:
    def __init__(self, root: Path, budget: int = BUDGET):
        self.root = lock_down_dir(Path(root))
        self.budget = budget
        self._lock = FileLock(self.root / "cache.lock")
        with self._lock:
            for stale in self.root.glob("*.part"):
                stale.unlink(missing_ok=True)
            self._trim(0)
        (self.root / "cache.lock").chmod(0o600)

    @staticmethod
    def media_key(channel_id: int, message_id: int, document_id) -> str:
        return hashlib.sha256(f"slice/{channel_id}/{message_id}/{document_id}".encode()).hexdigest()[:40]

    def _file(self, media: str, offset: int) -> Path:
        return self.root / f"{media}.{offset // SLICE:08x}.bin"

    def _entries(self):
        found = []
        for path in self.root.glob("*.bin"):
            try:
                st = path.stat()
            except FileNotFoundError:
                continue
            found.append((st.st_mtime, path, _charge(st)))
        found.sort(key=lambda item: item[0])
        return found

    def _trim(self, incoming: int) -> None:
        entries = self._entries()
        total = sum(cost for _, _, cost in entries)
        for _, path, cost in entries:
            if total + incoming <= self.budget:
                break
            path.unlink(missing_ok=True)
            total -= cost

    def usage(self) -> int:
        with self._lock:
            return sum(cost for _, _, cost in self._entries())

    def load(self, media: str, offset: int, size: int) -> bytes | None:
        path = self._file(media, offset)
        with self._lock:
            try:
                data = path.read_bytes()
            except FileNotFoundError:
                return None
            if len(data) != size:
                path.unlink(missing_ok=True)
                return None
            os.utime(path)
            return data

    def save(self, media: str, offset: int, data: bytes) -> None:
        if not data or len(data) > SLICE or SLICE > self.budget:
            return
        path = self._file(media, offset)
        part = path.with_name(path.name + ".part")
        with self._lock:
            path.unlink(missing_ok=True)
            self._trim(max(SLICE, len(data)))
            try:
                fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                os.replace(part, path)
            finally:
                part.unlink(missing_ok=True)

    def forget(self, media: str, offset: int | None = None) -> None:
        with self._lock:
            targets = [self._file(media, offset)] if offset is not None else list(self.root.glob(f"{media}.*.bin"))
            for path in targets:
                path.unlink(missing_ok=True)
