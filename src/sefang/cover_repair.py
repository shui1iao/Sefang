"""Explicit-manifest, cover-only repair. No migrations, metadata writes or eviction.

Candidates must first pass the existing exact-work and cover chooser rules.
The caller keeps a private manifest, source evidence and per-work receipts.
"""
from dataclasses import dataclass
from contextlib import closing
import hashlib
import io
import os
from pathlib import Path
import sqlite3
import tempfile
import time

from filelock import FileLock
from PIL import Image

from . import codes
from .backfill import SKIP_FAMILIES
from .catalog import covers
from .catalog.found import is_same_work
from .catalog.web import literal_ok
from .tg.works import COVER_BUDGET, COVER_FILES, COVER_MAX, cover_name


@dataclass(frozen=True)
class CheckedCover:
    identity: str
    code: str
    data: bytes
    source: str
    size: tuple[int, int]
    found: tuple


def validate_source(code, found, url):
    if not found or any(not is_same_work(code, f) for f in found):
        raise ValueError('identity mismatch')
    allowed = [p.url for p in covers.official_picks(code, found) + covers.mgstage_guesses(code)]
    # Same members as the existing chooser, not a broader fallback source list.
    community = [f for f in found if f.site in ('avbase', 'javbus', 'javdb', 'avsox')]
    allowed += [p.url for p in covers.usable(code, [covers.pick(u) for f in community for u in f.covers])]
    if url not in allowed or not literal_ok(url) or covers.is_javdb(url):
        raise ValueError('source rejected')


def select_cover(code, found, web):
    """Do not accept another release, an unknown site or a new community policy."""
    if not found or any(not is_same_work(code, f) for f in found):
        raise ValueError('identity mismatch')
    chosen = covers.choose(web, code, found)
    if chosen is None:
        return None
    pick, size, data = chosen
    validate_source(code, found, pick.url)
    return CheckedCover(codes.identity(code), code, data, pick.url, size, tuple(found))


def selected_missing(db_path, root, manifest):
    """Read-only selection; no Store constructors and no broad LIMIT selection."""
    if len({m['identity'] for m in manifest}) != len(manifest):
        raise ValueError('duplicate manifest identity')
    with closing(sqlite3.connect('file:' + str(db_path) + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        out = []
        for m in manifest:
            row = db.execute('SELECT * FROM tg_work WHERE identity=?', (m['identity'],)).fetchone()
            if not row or row['code'] != m['code'] or codes.identity(row['code']) != row['identity']:
                raise ValueError('manifest identity mismatch')
            if row['content_type'] in SKIP_FAMILIES:
                status = 'unsupported'
            elif row['cover_file'] or (Path(root) / cover_name(row['identity'])).exists():
                status = 'already_present'
            else:
                status = 'missing'
            out.append((dict(row), status))
        return out


def install_missing(db_path, root, manifest, image: CheckedCover, *, budget=COVER_BUDGET, files=COVER_FILES):
    """Never replace files or evict. Only necessary cover columns are updated."""
    matches = [m for m in manifest if m['identity'] == image.identity and m['code'] == image.code]
    if len(matches) != 1 or codes.identity(image.code) != image.identity:
        raise ValueError('outside manifest or identity mismatch')
    validate_source(image.code, image.found, image.source)
    if covers.names_other_work(image.code, image.source):
        raise ValueError('source rejected')
    if not image.data or len(image.data) > COVER_MAX:
        raise ValueError('cover too large or empty')
    with Image.open(io.BytesIO(image.data)) as im:
        if (im.format not in ('JPEG', 'PNG', 'WEBP') or getattr(im, 'is_animated', False)
                or im.width * im.height > 40_000_000 or im.size != tuple(image.size) or im.width < covers.NARROW):
            raise ValueError('unsupported image or dimensions')
        im.load()
        mime = Image.MIME[im.format]
    root = Path(root)
    name = cover_name(image.identity)
    target = root / name
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with FileLock(root / 'catalog.lock'), closing(sqlite3.connect(db_path, timeout=15)) as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT code,content_type,cover_file FROM tg_work WHERE identity=?', (image.identity,)).fetchone()
        if not row or row[0] != image.code or row[1] in SKIP_FAMILIES:
            raise ValueError('work changed or unsupported')
        if row[2] or target.exists() or target.is_symlink():
            raise FileExistsError('cover already present')
        entries = [p.stat() for p in root.glob('*.cover')]
        used = sum(max(s.st_size, s.st_blocks * 512) for s in entries)
        incoming = -(-len(image.data) // 4096) * 4096
        if used + incoming > min(budget, COVER_BUDGET) or len(entries) + 1 > min(files, COVER_FILES):
            raise ValueError('cover budget full; no eviction permitted')
        fd, temp = tempfile.mkstemp(prefix='.repair-', suffix='.part', dir=root)
        linked = False
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(image.data)
                f.flush()
                os.fsync(f.fileno())
            actual = Path(temp).stat()
            if used + max(actual.st_size, actual.st_blocks * 512) > min(budget, COVER_BUDGET):
                raise ValueError('cover budget full; no eviction permitted')
            os.link(temp, target)  # atomic no-replace, unlike rename/os.replace
            linked = True
            changed = db.execute("UPDATE tg_work SET cover_state='installed',cover_file=?,cover_mime=?,cover_source=?,"
                                 "cover_width=?,cover_height=?,cover_checked_at=? WHERE identity=? AND cover_file=''",
                                 (name, mime, image.source, *image.size, time.time(), image.identity)).rowcount
            if changed != 1:
                raise RuntimeError('work changed')
            db.commit()
        except BaseException:
            db.rollback()
            if linked:
                target.unlink()
            raise
        finally:
            Path(temp).unlink(missing_ok=True)
    return {'code': image.code, 'identity': image.identity, 'file': name, 'bytes': len(image.data),
            'sha256': hashlib.sha256(image.data).hexdigest(), 'mime': mime, 'size': list(image.size), 'source': image.source}
