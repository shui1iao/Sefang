"""Performer portraits for the actors shown on the site.

A portrait is installed only after the person's identity is pinned down by an
official catalogue (DMM / r18.dev performer id credited on one of *our* works
under exactly that name), or by the JavDB performer linked from an exactly
matching work page.  Name-only matches, the first of several namesakes, or
faces cut out of covers are never used.  Files are capped at 2 MiB each,
64 MiB and 512 files in total.
"""
from __future__ import annotations

import io
import json
import os
import re
import threading
import time
from collections import Counter
from urllib.parse import quote

from PIL import Image

from .repository import AMATEUR
from .catalog import sites
from .catalog.web import HoldBook, Missing, Refused, Spacer, Unreachable, Web

TOTAL = 64 * 1048576
SINGLE = 2 * 1048576
MAX_FILES = 512
GALLERY_INDEX = "https://raw.githubusercontent.com/gfriends/gfriends/master/Filetree.json"
GALLERY_FILES = "https://raw.githubusercontent.com/gfriends/gfriends/master/Content/"
_PLACEHOLDER = re.compile(r"(?:now_?printing|noimage|no_image|printing)", re.I)
_DESCRIPTIVE = re.compile(r"\d|歳|美女|素人|人妻|女子|ちゃん$")


_ALIAS = re.compile(r"\s*[（(]([^）)]*)[）)]\s*")


def same_name(credited: str, ours: str) -> bool:
    """Exact name, or the main name / bracketed alias of a credit such as '藤咲まい（藤咲舞）'."""
    credited, ours = (credited or "").strip(), (ours or "").strip()
    if not credited or not ours:
        return False
    if credited == ours:
        return True
    main = _ALIAS.sub("", credited).strip()
    aliases = [a.strip() for a in _ALIAS.findall(credited)]
    return ours == main or ours in aliases


def too_generic(name: str) -> bool:
    """Short kana-only given names and descriptive labels cannot identify a person on their own."""
    name = (name or "").strip()
    if not name or _DESCRIPTIVE.search(name):
        return True
    kana_only = re.fullmatch(r"[぀-ヿー・\s]+", name) is not None
    return kana_only and len(name.replace(" ", "")) <= 4


def gallery_index(body: bytes) -> dict[str, list[tuple[str, str]]]:
    """name -> [(folder, file)] with the curated folders (prefix 0-8) first."""
    tree = json.loads(body)["Content"]
    out: dict[str, list[tuple[str, str]]] = {}
    for folder, items in tree.items():
        for shown, stored in items.items():
            key = " ".join(shown.rsplit(".", 1)[0].split()).lower()
            out.setdefault(key, []).append((folder, stored.split("?")[0]))
    order = "0123456789abcdefghijklmnopqrstuvwxyz"
    for rows in out.values():
        rows.sort(key=lambda r: (order.find(r[0][:1].lower()) if r[0][:1].lower() in order else 99, r[0], r[1]))
    return out


class Portraits:
    def __init__(self, repo, *, web_factory=None):
        self.repo = repo
        self.root = repo.root / "avatars"
        self.root.mkdir(mode=0o700, exist_ok=True)
        self.root.chmod(0o700)
        self.stop = threading.Event()
        holds_dir = repo.config.candidate_root / "telegram-catalog" / "source-state"
        self.holds = HoldBook(holds_dir if holds_dir.is_dir() else None)
        self.spacer = Spacer()
        self.web_factory = web_factory or (lambda: Web(holds=self.holds, spacer=self.spacer, stop=self.stop,
                                                       max_requests=60, max_bytes=40 * 1048576, seconds=180))
        self._gallery = None

    # ---- storage
    def install(self, ident: str, body: bytes) -> tuple[str, str]:
        if len(body) > SINGLE:
            raise ValueError("image too large")
        with Image.open(io.BytesIO(body)) as im:
            if im.format not in ("JPEG", "PNG", "WEBP") or getattr(im, "is_animated", False) or im.width * im.height > 12_000_000:
                raise ValueError("not a portrait image")
            im.load()
            mime = Image.MIME[im.format]
            if min(im.size) < 48:
                raise ValueError("portrait too small")
        name = ident + ".img"
        path = self.root / name
        present = list(self.root.glob("*.img"))
        used = sum(p.stat().st_size for p in present if p != path)
        if used + len(body) > TOTAL or (not path.exists() and len(present) >= MAX_FILES):
            raise ValueError("portrait storage full")
        part = path.with_name(name + ".part")
        fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as out:
            out.write(body)
            out.flush()
            os.fsync(out.fileno())
        os.replace(part, path)
        path.chmod(0o600)
        return name, mime

    def record(self, ident, state, file="", mime="", external="", source=""):
        with self.repo.local() as db:
            db.execute("UPDATE entity SET avatar_state=?,avatar_file=?,avatar_mime=?,external_id=?,avatar_source=?,"
                       "checked_at=?,attempts=attempts+1 WHERE id=? AND (avatar_file='' OR avatar_file IS NULL)",
                       (state, file, mime, external, source, time.time(), ident))

    # ---- evidence
    def _works(self, name: str) -> list[tuple[str, list]]:
        where, args = self.repo.scope()
        with self.repo.read() as db:
            rows = db.execute("SELECT DISTINCT w.code,w.sources FROM tg_video v JOIN tg_identification i ON "
                              "i.channel_id=v.channel_id AND i.message_id=v.message_id JOIN tg_work w ON w.identity=i.identity "
                              "WHERE " + where + " AND EXISTS(SELECT 1 FROM json_each(w.metadata,'$.performers') WHERE value=?) "
                              "ORDER BY w.code", [*args, name]).fetchall()
        return [(r["code"], json.loads(r["sources"] or "[]")) for r in rows][:4]

    def _cached(self, key: str, make):
        with self.repo.local() as db:
            row = db.execute("SELECT payload FROM avatar_work_cache WHERE content_id=?", (key,)).fetchone()
        if row:
            return json.loads(row[0])
        value = make()
        with self.repo.local() as db:
            db.execute("INSERT OR REPLACE INTO avatar_work_cache VALUES(?,?,?)", (key, json.dumps(value, ensure_ascii=False), time.time()))
        return value

    def _official_cast(self, web: Web, code: str) -> list[dict]:
        """Credited performers of a work from DMM (falling back to r18.dev): [{name,id,image,via}]."""
        def ask():
            for reader in (sites.dmm, sites.r18dev):
                try:
                    found = reader(code, web)
                except Missing:
                    continue
                cast = [{"name": c.get("name", ""), "id": str(c.get("id") or ""), "image": c.get("image", ""), "via": found.site}
                        for c in found.cast if c.get("id")]
                if cast:
                    return cast
            return []
        return self._cached("own:official:" + code, ask)

    def _javdb_cast(self, web: Web, code: str) -> list[dict]:
        def ask():
            try:
                found = sites.javdb(code, web)
            except Missing:
                return []
            return [{"name": c.get("name", ""), "id": c.get("javdb", ""), "via": "javdb"} for c in found.cast if c.get("javdb")]
        return self._cached("own:javdb:" + code, ask)

    def _fetch(self, web: Web, url: str, referer: str) -> bytes:
        reply = web.fetch(url, referer=referer, limit=SINGLE, image=True)
        if _PLACEHOLDER.search(reply.url):
            raise Missing("placeholder portrait")
        return reply.body

    def _gallery_rows(self, web: Web, name: str):
        if self._gallery is None:
            self._gallery = gallery_index(web.fetch(GALLERY_INDEX, limit=16 * 1048576).body)
        rows = self._gallery.get(" ".join(name.split()).lower(), [])
        return [r for r in rows if r[0][:1] in "12345678" and not r[1].startswith("AI-Fix-")]

    def _javdb_portrait(self, web: Web, actor_id: str) -> str:
        page = web.fetch("https://javdb.com/actors/" + quote(actor_id), referer="https://javdb.com/").text()
        m = re.search(r'class="avatar"[^>]*style="[^"]*url\((https://[^)]+)\)', page) or \
            re.search(r'<img[^>]+class="avatar"[^>]+src="(https://[^"]+)"', page)
        if not m or "/actor_avatar" in m.group(1) and "noavatar" in m.group(1):
            raise Missing("no javdb portrait")
        return m.group(1)

    # ---- one performer
    def process(self, actor: dict) -> str:
        name = actor["name"].strip()
        if name == AMATEUR:
            self.record(actor["id"], "not_applicable")
            return "not_applicable"
        web = self.web_factory()
        trouble = []
        try:
            official = []
            for code, _ in self._works(name):
                try:
                    official += [c for c in self._official_cast(web, code) if same_name(c["name"], name)]
                except (Unreachable, Refused, OSError, ValueError) as error:
                    trouble.append(type(error).__name__)
                if self.stop.is_set():
                    return "stopped"
            ids = {c["id"] for c in official}
            if len(ids) > 1:
                self.record(actor["id"], "ambiguous")
                return "ambiguous"
            if ids:
                person = official[0]["id"]
                for c in official:
                    if c.get("image"):
                        try:
                            file, mime = self.install(actor["id"], self._fetch(web, c["image"], "https://www.dmm.co.jp/"))
                            self.record(actor["id"], "ready", file, mime, person, c["image"])
                            return "ready"
                        except Missing:
                            pass
                        except (Unreachable, Refused, OSError, ValueError) as error:
                            trouble.append(type(error).__name__)
                try:
                    for folder, file_name in self._gallery_rows(web, name)[:1]:
                        url = GALLERY_FILES + quote(folder) + "/" + quote(file_name)
                        file, mime = self.install(actor["id"], self._fetch(web, url, ""))
                        self.record(actor["id"], "ready", file, mime, person, url)
                        return "ready"
                except Missing:
                    pass
                except (Unreachable, Refused, OSError, ValueError, KeyError) as error:
                    trouble.append(type(error).__name__)
            elif not too_generic(name):
                linked = []
                for code, _ in self._works(name):
                    try:
                        linked += [c for c in self._javdb_cast(web, code) if same_name(c["name"], name)]
                    except (Unreachable, Refused, OSError, ValueError) as error:
                        trouble.append(type(error).__name__)
                jids = {c["id"] for c in linked}
                if len(jids) > 1:
                    self.record(actor["id"], "ambiguous")
                    return "ambiguous"
                if jids:
                    jid = next(iter(jids))
                    try:
                        url = self._javdb_portrait(web, jid)
                        file, mime = self.install(actor["id"], self._fetch(web, url, "https://javdb.com/"))
                        self.record(actor["id"], "ready", file, mime, "javdb:" + jid, url)
                        return "ready"
                    except Missing:
                        pass
                    except (Unreachable, Refused, OSError, ValueError) as error:
                        trouble.append(type(error).__name__)
            state = "temporary_error" if trouble else "unavailable"
            self.record(actor["id"], state, external=next(iter(ids), ""))
            return state
        finally:
            web.close()

    def run(self, *, include_missing=False) -> dict:
        states = ("pending", "unavailable", "temporary_error", "ambiguous") if include_missing else ("pending",)
        with self.repo.local() as db:
            actors = [dict(r) for r in db.execute(
                "SELECT * FROM entity WHERE kind='actors' AND video_count>0 AND (avatar_file='' OR avatar_file IS NULL) AND avatar_state IN (%s) "
                "ORDER BY video_count DESC,id" % ",".join("?" * len(states)), states)]
        results = {}
        for actor in actors:
            if self.stop.is_set():
                break
            try:
                results[actor["name"]] = self.process(actor)
            except Exception as error:  # one performer must not stop the batch
                results[actor["name"]] = "error:" + type(error).__name__
        return {"processed": results, **self.summary()}

    def summary(self) -> dict:
        with self.repo.local() as db:
            rows = db.execute("SELECT avatar_state,avatar_file FROM entity WHERE kind='actors' AND video_count>0").fetchall()
        return {"actors": len(rows), "states": dict(Counter(r["avatar_state"] for r in rows)),
                "actual_images": sum(bool(r["avatar_file"] and (self.root / r["avatar_file"]).is_file()) for r in rows),
                "bytes": sum(p.stat().st_size for p in self.root.glob("*.img")), "limit": TOTAL, "single_limit": SINGLE}
