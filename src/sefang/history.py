"""Own-only local history. Never opens Telegram/auth/catalog SQLite for writes.

Delete barriers persist independently of entries. Old writer capabilities cannot
resurrect a deletion, including requests queued before delete/clear. A fresh
player obtains a fresh context; context creation alone never records a viewing.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import math
import os
import secrets
import sqlite3
import threading
import time

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import Field, StrictFloat, StrictInt, StrictStr
from .auth import Input, LIFETIME

router = APIRouter()
MAX_SECONDS = 172800


class HistoryStore:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.parent.is_symlink() or path.is_symlink():
            raise ValueError('unsafe history storage')
        path.parent.chmod(0o700)
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        path.chmod(0o600)
        self.lock = threading.Lock()
        self.writers = {}
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS history(
              id TEXT PRIMARY KEY, account_id INTEGER NOT NULL, work_id TEXT NOT NULL,
              anchor_cid INTEGER NOT NULL, anchor_mid INTEGER NOT NULL,
              part_cid INTEGER NOT NULL, part_mid INTEGER NOT NULL,
              position REAL NOT NULL, duration REAL NOT NULL, completed INTEGER NOT NULL,
              title TEXT NOT NULL, updated_ns INTEGER NOT NULL,
              UNIQUE(account_id,work_id));
            CREATE INDEX IF NOT EXISTS history_recent ON history(account_id,updated_ns DESC,id);
            CREATE TABLE IF NOT EXISTS generations(account_id INTEGER PRIMARY KEY,version INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS deletions(account_id INTEGER NOT NULL,work_id TEXT NOT NULL,version INTEGER NOT NULL,
              PRIMARY KEY(account_id,work_id));
            ''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def versions(self, db, account, work):
        a = db.execute('SELECT version FROM generations WHERE account_id=?', (account,)).fetchone()
        b = db.execute('SELECT version FROM deletions WHERE account_id=? AND work_id=?', (account, work)).fetchone()
        return (a[0] if a else 0, b[0] if b else 0)

    def context(self, person, group):
        with self.lock, self.db() as db:
            now = time.monotonic()
            self.writers = {k:v for k,v in self.writers.items() if v.created > now-LIFETIME}
            same = [k for k,v in self.writers.items() if v.session == person.session]
            # Bounded transient contexts, not a retention cap on history.
            for key in same[:-31]:
                del self.writers[key]
            key = secrets.token_urlsafe(24)
            self.writers[key] = Writer(person.id, person.session, group.id,
                                       self.versions(db, person.id, group.id), now)
            return key

    def write(self, person, data, group, part):
        with self.lock, self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            writer = self.writers.get(data.context)
            if not writer or (writer.account,writer.session,writer.work) != (person.id,person.session,group.id):
                raise HTTPException(409, '记录窗口已失效，重新打开作品后可继续记录')
            if writer.versions != self.versions(db,person.id,group.id):
                raise HTTPException(409, '历史已删除，重新打开作品并播放后才会再次记录')
            # A newly opened player takes precedence only after it really plays.
            # An old page's delayed first/final request cannot overwrite its progress.
            if any(v.account == person.id and v.work == group.id and v.started and v.created > writer.created
                   for v in self.writers.values()):
                raise HTTPException(409, '较新播放窗口正在记录，旧窗口不再覆盖进度')
            if data.sequence <= writer.sequence:
                return {'ok':True, 'stale':True}
            if not writer.started and data.event != 'playing':
                raise HTTPException(409, '尚未开始播放')
            duration = float(part['duration']) if valid_seconds(part.get('duration')) else data.duration
            duration = min(duration,data.duration)
            if data.position > duration+1:
                raise HTTPException(422, '播放位置超出本段')
            position = min(duration,data.position)
            row = group.representative
            db.execute('''INSERT INTO history VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(account_id,work_id) DO UPDATE SET part_cid=excluded.part_cid,part_mid=excluded.part_mid,
              position=excluded.position,duration=excluded.duration,completed=excluded.completed,
              title=excluded.title,updated_ns=excluded.updated_ns''',
              (secrets.token_hex(16),person.id,group.id,row['channel_id'],row['message_id'],
               part['channel_id'],part['message_id'],position,duration,int(data.event=='ended' or position>=duration-.1),
               str(row.get('title') or '视频')[:1000],time.time_ns()))
            writer.sequence,writer.started = data.sequence,True
        return {'ok':True}

    def page(self, account, page, limit):
        with self.db() as db:
            db.execute('BEGIN')
            total = db.execute('SELECT count(*) FROM history WHERE account_id=?',(account,)).fetchone()[0]
            rows = db.execute('SELECT * FROM history WHERE account_id=? ORDER BY updated_ns DESC,id LIMIT ? OFFSET ?',
                              (account,limit,(page-1)*limit)).fetchall()
        return dict(items=[dict(r) for r in rows],total=total,page=page,pages=(total+limit-1)//limit)

    def get(self, account, ident):
        with self.db() as db:
            row = db.execute('SELECT * FROM history WHERE account_id=? AND id=?',(account,ident)).fetchone()
        if not row:
            raise HTTPException(404,'历史未取得')
        return dict(row)

    def delete(self, account, ident):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT work_id FROM history WHERE account_id=? AND id=?',(account,ident)).fetchone()
            if not row:
                raise HTTPException(404,'历史未取得')
            db.execute('DELETE FROM history WHERE account_id=? AND id=?',(account,ident))
            db.execute('INSERT INTO deletions VALUES(?,?,1) ON CONFLICT(account_id,work_id) DO UPDATE SET version=version+1',(account,row[0]))

    def clear(self, account):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM history WHERE account_id=?',(account,))
            db.execute('INSERT INTO generations VALUES(?,1) ON CONFLICT(account_id) DO UPDATE SET version=version+1',(account,))


@dataclass
class Writer:
    account: int
    session: str
    work: str
    versions: tuple
    created: float
    sequence: int = 0
    started: bool = False


def valid_seconds(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and 0 < value <= MAX_SECONDS


def group_for(repo, config, cid, mid):
    if cid not in config.channels:
        raise HTTPException(404)
    group = repo.snapshot().by_message.get((cid,mid))
    if group is None:
        raise HTTPException(404,'作品当前不可用')
    return group


def resolve(row, repo):
    snap = repo.snapshot()
    group = snap.by_message.get((row['anchor_cid'],row['anchor_mid']))
    # No inference/remapping if the authoritative grouping has changed.
    if group is None or group.id != row['work_id']:
        return None,None,'作品当前不可用'
    part = next((r for r in group.messages if (r['channel_id'],r['message_id']) == (row['part_cid'],row['part_mid']) and r.get('available')),None)
    if part:
        return group,part,'已看完，从本段开头恢复' if row['completed'] else ''
    part = next((r for r in group.parts if r.get('available')),None)
    return group,part,'原分段不可用，从首个可用分段开头恢复' if part else '作品当前不可用'


def public_row(row,repo):
    group,part,note = resolve(row,repo)
    card = repo.card(group) if group else None
    return dict(id=row['id'],work_id=row['work_id'],title=row['title'],video=card,
                part_number=(group.index_of(row['part_cid'],row['part_mid'])+1) if group and group.index_of(row['part_cid'],row['part_mid']) is not None else None,
                position=row['position'],duration=row['duration'],completed=bool(row['completed']),
                updated_at=row['updated_ns']//1000000,available=part is not None,note=note,
                channel_id=part['channel_id'] if part else None,message_id=part['message_id'] if part else None)


class ContextInput(Input):
    channel_id: StrictInt = Field(gt=0,lt=2**53)
    message_id: StrictInt = Field(gt=0,lt=2**53)


class ProgressInput(ContextInput):
    context: StrictStr = Field(pattern=r'^[A-Za-z0-9_-]{32}$')
    sequence: StrictInt = Field(gt=0,lt=2**53)
    position: StrictFloat = Field(ge=0,le=MAX_SECONDS,allow_inf_nan=False)
    duration: StrictFloat = Field(gt=0,le=MAX_SECONDS,allow_inf_nan=False)
    event: StrictStr = Field(pattern=r'^(playing|progress|pause|seeked|ended|final)$')


@router.post('/api/history/context')
def context(data: ContextInput,request: Request):
    group = group_for(request.app.state.repository,request.app.state.config,data.channel_id,data.message_id)
    return {'context':request.app.state.history.context(request.state.principal,group),'work_id':group.id}


@router.post('/api/history/progress')
def progress(data: ProgressInput,request: Request):
    group = group_for(request.app.state.repository,request.app.state.config,data.channel_id,data.message_id)
    part = next((r for r in group.messages if (r['channel_id'],r['message_id']) == (data.channel_id,data.message_id)),None)
    if not part or not part.get('available'):
        raise HTTPException(404)
    return request.app.state.history.write(request.state.principal,data,group,part)


@router.get('/api/history')
def listing(request: Request,page:int=Query(1,ge=1,le=1000000000),limit:int=Query(24,ge=1,le=60)):
    result = request.app.state.history.page(request.state.principal.id,page,limit)
    result['items'] = [public_row(row,request.app.state.repository) for row in result['items']]
    return result


@router.get('/api/history/{ident}/resume')
def resume(ident:str,request:Request):
    row = request.app.state.history.get(request.state.principal.id,ident)
    group,part,note = resolve(row,request.app.state.repository)
    if part is None:
        raise HTTPException(404,'作品当前不可用；历史仍可删除')
    reset = bool(note)
    duration = float(part['duration']) if valid_seconds(part.get('duration')) else row['duration']
    return dict(id=row['id'],account_id=request.state.principal.id,work_id=group.id,
                channel_id=part['channel_id'],message_id=part['message_id'],
                position=0 if reset else min(row['position'],max(0,duration-.1)),note=note)


@router.post('/api/history/{ident}/delete')
def delete(ident:str,data:Input,request:Request):
    request.app.state.history.delete(request.state.principal.id,ident)
    return {'ok':True}


@router.post('/api/history/clear')
def clear(data:Input,request:Request):
    request.app.state.history.clear(request.state.principal.id)
    return {'ok':True}
