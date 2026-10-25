"""SQLite index of the authorised channel(s).

The table layout is the one already present in the data root; it is only created
when missing (fresh test roots) and never altered.  Every stored video gets an
identification row and, when a single work is recognised, a work row that the
metadata jobs fill in later.
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .. import codes

_TABLES = """
CREATE TABLE IF NOT EXISTS tg_channel(
 id INTEGER PRIMARY KEY,title TEXT NOT NULL,history_cursor INTEGER DEFAULT 0,history_done INTEGER DEFAULT 0,
 high_water INTEGER DEFAULT 0,state TEXT DEFAULT 'idle',error TEXT DEFAULT '',scanned INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS tg_video(
 channel_id INTEGER NOT NULL,message_id INTEGER NOT NULL,document_id TEXT NOT NULL,title TEXT NOT NULL,
 caption TEXT NOT NULL,date TEXT NOT NULL,size INTEGER NOT NULL,duration REAL NOT NULL,width INTEGER,height INTEGER,
 mime TEXT NOT NULL,protected INTEGER NOT NULL,available INTEGER DEFAULT 1,PRIMARY KEY(channel_id,message_id));
CREATE INDEX IF NOT EXISTS tg_video_date ON tg_video(date DESC);
CREATE TABLE IF NOT EXISTS tg_message_album(
 channel_id INTEGER NOT NULL,message_id INTEGER NOT NULL,grouped_id TEXT NOT NULL,
 PRIMARY KEY(channel_id,message_id));
CREATE INDEX IF NOT EXISTS tg_message_album_group ON tg_message_album(channel_id,grouped_id);
CREATE TABLE IF NOT EXISTS tg_album_caption(
 channel_id INTEGER NOT NULL,message_id INTEGER NOT NULL,caption TEXT NOT NULL,
 PRIMARY KEY(channel_id,message_id));
CREATE TABLE IF NOT EXISTS tg_cover_photo(
 channel_id INTEGER NOT NULL,message_id INTEGER NOT NULL,grouped_id TEXT NOT NULL,
 identity TEXT NOT NULL,photo_id TEXT NOT NULL,PRIMARY KEY(channel_id,message_id));
CREATE INDEX IF NOT EXISTS tg_cover_photo_work ON tg_cover_photo(identity);
CREATE TABLE IF NOT EXISTS tg_cover_pending(identity TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS tg_identification(
 channel_id INTEGER NOT NULL,message_id INTEGER NOT NULL,fingerprint TEXT NOT NULL,state TEXT NOT NULL,
 code TEXT NOT NULL,identity TEXT NOT NULL,candidates TEXT NOT NULL,evidence TEXT NOT NULL,updated_at REAL NOT NULL,
 PRIMARY KEY(channel_id,message_id));
CREATE INDEX IF NOT EXISTS tg_identification_work ON tg_identification(identity);
CREATE TABLE IF NOT EXISTS tg_work(
 identity TEXT PRIMARY KEY,code TEXT NOT NULL,content_type TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'pending',
 metadata TEXT NOT NULL DEFAULT '{}',sources TEXT NOT NULL DEFAULT '[]',checked_at REAL DEFAULT 0,attempts INTEGER DEFAULT 0,
 next_retry REAL DEFAULT 0,error TEXT DEFAULT '',cover_state TEXT NOT NULL DEFAULT 'pending',cover_file TEXT DEFAULT '',
 cover_mime TEXT DEFAULT '',cover_source TEXT DEFAULT '',cover_width INTEGER DEFAULT 0,cover_height INTEGER DEFAULT 0,
 cover_checked_at REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS tg_catalog_control(id INTEGER PRIMARY KEY,paused INTEGER DEFAULT 0);
INSERT OR IGNORE INTO tg_catalog_control(id,paused) VALUES(1,0);
"""
VIDEO_COLUMNS = ("channel_id", "message_id", "document_id", "title", "caption", "date", "size", "duration",
                 "width", "height", "mime", "protected", "available")
PLAYABLE_MIME = frozenset({"video/mp4", "video/webm", "video/quicktime", "video/x-matroska", "video/mpeg", "video/3gpp"})
NOT_FETCHED_TYPES = frozenset({"other", "kmib", "unknown"})
RECHECK_MISSING_AFTER = 7 * 86400


def lock_down_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def set_album(db, channel_id: int, message_id: int, grouped_id) -> int:
    """Source relationship only, separate from tg_video and identification. Never infer an album.

    Used in the same transaction as normal history/new/edit indexing. Text keeps
    Telegram's signed 64-bit grouped_id exact, without a floating-point round trip.
    """
    if grouped_id is None:
        return db.execute("DELETE FROM tg_message_album WHERE channel_id=? AND message_id=?",
                          (channel_id, message_id)).rowcount
    if isinstance(grouped_id, bool) or not isinstance(grouped_id, (int, str)):
        raise ValueError("invalid Telegram grouped_id")
    text = str(grouped_id)
    if not text.lstrip('-').isascii() or not text.lstrip('-').isdigit() or not -(2**63) <= int(text) < 2**63:
        raise ValueError("invalid Telegram grouped_id")
    return db.execute("INSERT INTO tg_message_album VALUES(?,?,?) ON CONFLICT(channel_id,message_id) "
                      "DO UPDATE SET grouped_id=excluded.grouped_id WHERE grouped_id<>excluded.grouped_id",
                      (channel_id, message_id, str(int(text)))).rowcount


def video_from_message(channel_id: int, message, *, protected: bool = False) -> dict | None:
    """Row for tg_video, or None when the message carries no video document."""
    doc = getattr(message, "document", None)
    if not doc:
        return None
    attrs = list(getattr(doc, "attributes", None) or [])
    video = next((a for a in attrs if type(a).__name__ == "DocumentAttributeVideo"), None)
    mime = getattr(doc, "mime_type", "") or ""
    if video is None and not mime.startswith("video/"):
        return None
    filename = next((a.file_name for a in attrs if getattr(a, "file_name", None) is not None), "")
    text = getattr(message, "message", "") or ""
    return {
        "channel_id": channel_id, "message_id": message.id, "document_id": str(doc.id),
        "title": filename or text.split("\n")[0][:180] or f"视频 {message.id}",
        "caption": text, "date": message.date.isoformat(), "size": doc.size,
        "duration": float(getattr(video, "duration", 0) or 0), "width": getattr(video, "w", 0),
        "height": getattr(video, "h", 0), "mime": mime if mime in PLAYABLE_MIME else "application/octet-stream",
        "protected": int(bool(protected or getattr(message, "noforwards", False))), "available": 1,
        "grouped_id": getattr(message, "grouped_id", None),  # attached relationship, not a VIDEO_COLUMN
    }


def photo_fact(message):
    """Only an actual photo with one explicit work code; captions alone are not media."""
    photo = getattr(message, 'photo', None)
    found = codes.numbers_in(getattr(message, 'message', '') or '')
    if not photo or not getattr(photo, 'id', None) or len(found) != 1 or getattr(message, 'grouped_id', None) is None:
        return None
    return {'identity': codes.identity(found[0]), 'photo_id': str(photo.id)}


def album_context_from_message(channel_id: int, message) -> dict:
    """Non-video source context only. No gid means clear any former album source."""
    return {'channel_id': channel_id, 'message_id': message.id,
            'grouped_id': getattr(message, 'grouped_id', None),
            'caption': getattr(message, 'message', '') or '', 'photo': photo_fact(message)}


class ChannelIndex:
    def __init__(self, path: Path):
        self.path = Path(path)
        lock_down_dir(self.path.parent)
        with self.session() as db:
            db.executescript(_TABLES)
            self._identify_missing(db)
        self.path.chmod(0o600)

    @contextmanager
    def session(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    # ---- channels
    def channel_row(self, channel_id: int) -> dict | None:
        with self.session() as db:
            row = db.execute("SELECT * FROM tg_channel WHERE id=?", (channel_id,)).fetchone()
        return dict(row) if row else None

    def ensure_channel(self, channel_id: int, title: str) -> None:
        with self.session() as db:
            db.execute("INSERT INTO tg_channel(id,title) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title",
                       (channel_id, title))

    def set_state(self, channel_id: int, state: str, error: str = "") -> None:
        with self.session() as db:
            db.execute("UPDATE tg_channel SET state=?,error=? WHERE id=?", (state, error, channel_id))

    # ---- videos
    def store(self, channel_id: int, rows: list[dict], *, scanned: int = 0, high_water: int = 0,
              cursor: int | None = None, done: bool = False, contexts: list[dict] = ()) -> int:
        """Upsert rows and move checkpoints in one transaction; returns how many rows changed."""
        changed = 0
        with self.session() as db:
            keys = {(r['channel_id'],r['message_id']) for r in [*rows,*contexts]}
            gids = {(cid,a[0]) for cid,mid in keys for a in db.execute(
                'SELECT grouped_id FROM tg_message_album WHERE channel_id=? AND message_id=?',(cid,mid))}
            for row in rows:
                changed += self._put(db, row)
            for context in contexts:
                changed += self._put_context(db, context)
            if changed:
                gids.update((r['channel_id'],str(r['grouped_id'])) for r in [*rows,*contexts] if r.get('grouped_id') is not None)
                self._queue_photos(db,gids)
            db.execute("UPDATE tg_channel SET high_water=max(high_water,?),scanned=scanned+?,error='' WHERE id=?",
                       (high_water, scanned, channel_id))
            if cursor is not None:
                db.execute("UPDATE tg_channel SET history_cursor=?,history_done=? WHERE id=?", (cursor, int(done), channel_id))
        return changed

    def _put_context(self, db, row: dict) -> int:
        """Current non-video caption + exact relation; never copy it into tg_video."""
        key = (row['channel_id'], row['message_id'])
        changed = db.execute('UPDATE tg_video SET available=0 WHERE channel_id=? AND message_id=? AND available<>0', key).rowcount
        changed += set_album(db, *key, row['grouped_id'])
        fact = row.get('photo') if row['grouped_id'] is not None else None
        if fact:
            changed += db.execute('INSERT INTO tg_cover_photo VALUES(?,?,?,?,?) ON CONFLICT(channel_id,message_id) '
                                  'DO UPDATE SET grouped_id=excluded.grouped_id,identity=excluded.identity,photo_id=excluded.photo_id '
                                  'WHERE grouped_id<>excluded.grouped_id OR identity<>excluded.identity OR photo_id<>excluded.photo_id',
                                  (*key,str(row['grouped_id']),fact['identity'],fact['photo_id'])).rowcount
        else:
            changed += db.execute('DELETE FROM tg_cover_photo WHERE channel_id=? AND message_id=?',key).rowcount
        if row['grouped_id'] is None:
            changed += db.execute('DELETE FROM tg_album_caption WHERE channel_id=? AND message_id=?', key).rowcount
        else:
            changed += db.execute('INSERT INTO tg_album_caption VALUES(?,?,?) ON CONFLICT(channel_id,message_id) '
                                  'DO UPDATE SET caption=excluded.caption WHERE caption<>excluded.caption',
                                  (*key, row['caption'])).rowcount
        return int(bool(changed))

    def _put(self, db, row: dict) -> int:
        context_changed = db.execute('DELETE FROM tg_cover_photo WHERE channel_id=? AND message_id=?',
                                     (row['channel_id'],row['message_id'])).rowcount
        context_changed += db.execute('DELETE FROM tg_album_caption WHERE channel_id=? AND message_id=?',
                                     (row['channel_id'], row['message_id'])).rowcount
        album_changed = set_album(db, row['channel_id'], row['message_id'],
                                  row['grouped_id'] if row['available'] else None) if 'grouped_id' in row else 0
        values = tuple(row[c] for c in VIDEO_COLUMNS)
        old = db.execute("SELECT * FROM tg_video WHERE channel_id=? AND message_id=?",
                         (row["channel_id"], row["message_id"])).fetchone()
        if old is None or tuple(old[c] for c in VIDEO_COLUMNS) != values:
            keep = ",".join(f"{c}=excluded.{c}" for c in VIDEO_COLUMNS[2:])
            db.execute(f"INSERT INTO tg_video({','.join(VIDEO_COLUMNS)}) VALUES({','.join('?' * len(VIDEO_COLUMNS))}) "
                       f"ON CONFLICT(channel_id,message_id) DO UPDATE SET {keep}", values)
            self._identify(db, row)
            return 1
        return int(bool(album_changed or context_changed))

    def _queue_photos(self, db, gids):
        # Event-driven only: never seed from old caption-only context or sweep ready works.
        for cid,gid in gids:
            for p in db.execute('SELECT identity FROM tg_cover_photo WHERE channel_id=? AND grouped_id=?',(cid,gid)).fetchall():
                db.execute('INSERT OR IGNORE INTO tg_cover_pending VALUES(?)',(p['identity'],))

    def photo_candidates(self, identity: str, channels) -> list[dict]:
        if not channels:return []
        marks=','.join('?'*len(channels))
        with self.session() as db:
            rows=db.execute(f"SELECT p.*,v.message_id AS video_id,v.document_id,v.title FROM tg_cover_photo p "
                "JOIN tg_message_album a ON a.channel_id=p.channel_id AND a.grouped_id=p.grouped_id "
                "JOIN tg_video v ON v.channel_id=a.channel_id AND v.message_id=a.message_id "
                "JOIN tg_identification i ON i.channel_id=v.channel_id AND i.message_id=v.message_id "
                f"WHERE p.identity=? AND p.channel_id IN ({marks}) AND v.available=1 AND i.state='identified' "
                "AND i.identity=p.identity ORDER BY p.message_id,v.message_id",[identity,*channels]).fetchall()
        out=[];seen=set()
        for r in rows:
            found=codes.numbers_in(r['title'],as_filename=True)
            if len(found)!=1 or codes.identity(found[0])!=identity or (r['channel_id'],r['message_id']) in seen:continue
            seen.add((r['channel_id'],r['message_id']));out.append(dict(r))
        return out

    def mark_gone(self, channel_id: int, message_id: int) -> None:
        with self.session() as db:
            db.execute('DELETE FROM tg_cover_photo WHERE channel_id=? AND message_id=?',(channel_id,message_id))
            set_album(db, channel_id, message_id, None)
            db.execute('DELETE FROM tg_album_caption WHERE channel_id=? AND message_id=?', (channel_id, message_id))
            db.execute("UPDATE tg_video SET available=0 WHERE channel_id=? AND message_id=? AND available<>0",
                       (channel_id, message_id))

    def video(self, channel_id: int, message_id: int) -> dict | None:
        with self.session() as db:
            row = db.execute("SELECT * FROM tg_video WHERE channel_id=? AND message_id=?", (channel_id, message_id)).fetchone()
        return dict(row) if row else None

    # ---- identification
    def _identify(self, db, row: dict) -> None:
        stamp = codes.message_fingerprint(row["title"], row["caption"], row["document_id"])
        known = db.execute("SELECT fingerprint FROM tg_identification WHERE channel_id=? AND message_id=?",
                           (row["channel_id"], row["message_id"])).fetchone()
        if known and known[0] == stamp:
            return
        found = codes.scan_message(row["title"], row["caption"])
        now = time.time()
        db.execute(
            "INSERT INTO tg_identification(channel_id,message_id,fingerprint,state,code,identity,candidates,evidence,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(channel_id,message_id) DO UPDATE SET fingerprint=excluded.fingerprint,"
            "state=excluded.state,code=excluded.code,identity=excluded.identity,candidates=excluded.candidates,"
            "evidence=excluded.evidence,updated_at=excluded.updated_at",
            (row["channel_id"], row["message_id"], stamp, found["state"], found["code"], found["identity"],
             json.dumps(found["candidates"]), json.dumps(found["evidence"]), now))
        if not found["identity"]:
            return
        initial = "unsupported" if found["content_type"] in NOT_FETCHED_TYPES else "pending"
        db.execute("INSERT OR IGNORE INTO tg_work(identity,code,content_type,state) VALUES(?,?,?,?)",
                   (found["identity"], found["code"], found["content_type"], initial))
        db.execute("UPDATE tg_work SET state='pending',attempts=0,next_retry=0 WHERE identity=? AND state='not_found' AND checked_at<?",
                   (found["identity"], now - RECHECK_MISSING_AFTER))

    def _identify_missing(self, db) -> None:
        rows = db.execute("SELECT v.* FROM tg_video v LEFT JOIN tg_identification i ON i.channel_id=v.channel_id "
                          "AND i.message_id=v.message_id WHERE i.message_id IS NULL").fetchall()
        for row in rows:
            self._identify(db, dict(row))
