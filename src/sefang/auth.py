"""Private account store. No Telegram state or catalog database is used here."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr
from starlette.responses import JSONResponse

COOKIE = "__Host-sefang_session"
LIFETIME = 24 * 3600
DEFAULT_RATE = 2097152
USERNAME = re.compile(r"[a-z][a-z0-9_.-]{2,31}\Z")
router = APIRouter()


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=131072, r=8, p=1, maxmem=256*1024*1024)
    return "scrypt$131072$8$1$" + salt.hex() + "$" + digest.hex()


def password_ok(password: str, encoded: str) -> bool:
    try:
        _, n, r, p, salt, digest = encoded.split("$")
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), maxmem=256*1024*1024)
        return hmac.compare_digest(actual.hex(), digest)
    except (ValueError, TypeError):
        return False


DUMMY = password_hash(secrets.token_urlsafe(24))


def valid_password(value: str):
    if not 12 <= len(value) <= 256:
        raise ValueError("密码须为 12–256 个字符")


def valid_username(value: str):
    if not USERNAME.fullmatch(value):
        raise ValueError("账号须为 3–32 位小写字母、数字或 . _ -，以字母开头")


@dataclass(frozen=True)
class Principal:
    id: int
    username: str
    role: str
    rate: int | None
    max_playbacks: int
    session: str
    csrf: str

    def public(self):
        return {"id": self.id, "username": self.username, "role": self.role,
                "rate_bps": self.rate, "max_playbacks": self.max_playbacks, "csrf": self.csrf}


class AuthStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.parent.is_symlink() or path.is_symlink():
            raise ValueError("unsafe auth storage")
        os.chmod(path.parent, 0o700)
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        os.chmod(path, 0o600)
        with self.db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS accounts(
              id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE,
              password TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','user')),
              enabled INTEGER NOT NULL DEFAULT 1,
              rate_bps INTEGER CHECK(rate_bps IS NULL OR rate_bps>0),
              max_playbacks INTEGER NOT NULL CHECK(max_playbacks>0));
            CREATE TABLE IF NOT EXISTS sessions(
              digest TEXT PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES accounts(id),
              expires INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS session_account ON sessions(account_id);
            CREATE TABLE IF NOT EXISTS attempts(key TEXT PRIMARY KEY, starts INTEGER NOT NULL, count INTEGER NOT NULL);
            """)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def bootstrap(self, username: str, password: str, max_playbacks: int):
        valid_username(username)
        valid_password(password)
        if max_playbacks < 1:
            raise ValueError("同时播放上限须大于 0")
        encoded = password_hash(password)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM accounts WHERE role='admin' OR username=?", (username,)).fetchone():
                raise ValueError("管理员或同名账号已存在；未覆盖")
            db.execute("INSERT INTO accounts(username,password,role,rate_bps,max_playbacks) VALUES(?,?,'admin',NULL,?)",
                       (username, encoded, max_playbacks))

    def authenticate(self, token: str) -> Principal | None:
        if not token or len(token) != 43:
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.db() as db:
            row = db.execute("SELECT a.* FROM sessions s JOIN accounts a ON a.id=s.account_id WHERE s.digest=? AND s.expires>? AND a.enabled=1",
                             (digest, int(time.time()))).fetchone()
        if not row:
            return None
        csrf = hashlib.sha256(("csrf:" + token).encode()).hexdigest()
        return Principal(row["id"], row["username"], row["role"], row["rate_bps"], row["max_playbacks"], digest, csrf)

    def login(self, username: str, password: str, address: str):
        now = int(time.time())
        # Neither key depends on whether the account exists. Never trust user supplied X-Forwarded-For.
        keys = [("u:" + hashlib.sha256(username.encode()).hexdigest(), 10),
                ("ip:" + hashlib.sha256(address.encode()).hexdigest(), 120)]
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM attempts WHERE starts<=?", (now-300,))
            db.execute("DELETE FROM sessions WHERE expires<=?", (now,))
            for key, maximum in keys:
                row = db.execute("SELECT count FROM attempts WHERE key=?", (key,)).fetchone()
                if row and row[0] >= maximum:
                    raise HTTPException(429, "登录尝试过多，请五分钟后再试", headers={"Retry-After": "300"})
            for key, _ in keys:
                db.execute("INSERT INTO attempts VALUES(?,?,1) ON CONFLICT(key) DO UPDATE SET count=count+1", (key, now))
            row = db.execute("SELECT * FROM accounts WHERE username=?", (username,)).fetchone()
        okay = password_ok(password, row["password"] if row else DUMMY)
        if not okay or not row or not row["enabled"]:
            raise HTTPException(401, "账号或密码不正确")
        token = secrets.token_urlsafe(32)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            # Recheck the password and enabled state after the expensive hash operation.
            current = db.execute("SELECT * FROM accounts WHERE id=?", (row["id"],)).fetchone()
            if not current or not current["enabled"] or current["password"] != row["password"]:
                raise HTTPException(401, "账号或密码不正确")
            db.execute("INSERT INTO sessions VALUES(?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), row["id"], now+LIFETIME))
        return token

    def logout(self, digest):
        with self.db() as db:
            db.execute("DELETE FROM sessions WHERE digest=?", (digest,))

    def accounts(self):
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT id,username,role,enabled,rate_bps,max_playbacks FROM accounts ORDER BY id")]

    def create(self, username, password, rate, maximum):
        valid_username(username)
        valid_password(password)
        encoded = password_hash(password)
        try:
            with self.db() as db:
                db.execute("INSERT INTO accounts(username,password,role,rate_bps,max_playbacks) VALUES(?,?,'user',?,?)",
                           (username, encoded, rate, maximum))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "账号已存在") from None

    def update(self, ident: int, fields: dict):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM accounts WHERE id=?", (ident,)).fetchone()
            if not row:
                raise HTTPException(404, "账号未取得")
            if row["role"] == "admin" and fields.get("enabled") is False:
                raise HTTPException(409, "管理员不可停用")
            for key, value in fields.items():
                if key not in {"enabled", "rate_bps", "max_playbacks", "password"}:
                    raise ValueError("unsupported account field")
                db.execute(f"UPDATE accounts SET {key}=? WHERE id=?", (value, ident))
            if fields.get("enabled") is False or "password" in fields:
                db.execute("DELETE FROM sessions WHERE account_id=?", (ident,))


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Login(Input):
    username: StrictStr = Field(min_length=1, max_length=64)
    password: StrictStr = Field(min_length=1, max_length=256)


class NewAccount(Input):
    username: StrictStr = Field(min_length=3, max_length=32)
    password: StrictStr = Field(min_length=12, max_length=256)
    rate_bps: StrictInt | None = Field(default=DEFAULT_RATE, gt=0, le=2**40)
    max_playbacks: StrictInt = Field(gt=0, le=2**31-1)


class AccountChange(Input):
    enabled: bool | None = None
    rate_bps: StrictInt | None = Field(default=None, gt=0, le=2**40)
    max_playbacks: StrictInt | None = Field(default=None, gt=0, le=2**31-1)


class PasswordChange(Input):
    password: StrictStr = Field(min_length=12, max_length=256)


def admin(request: Request):
    # This lookup is performed on every operation, never from a frontend-supplied role.
    person = request.app.state.auth.authenticate(request.cookies.get(COOKIE, ""))
    if not person:
        raise HTTPException(401, "请先登录")
    if person.role != "admin":
        raise HTTPException(403, "无权操作")
    return person


@router.post("/api/auth/login")
async def login(data: Login, request: Request):
    async with request.app.state.password_gate:
        token = await asyncio.to_thread(request.app.state.auth.login, data.username, data.password,
                                        request.client.host if request.client else "unknown")
    person = request.app.state.auth.authenticate(token)
    if person is None:
        raise HTTPException(401, "账号或密码不正确")
    response = JSONResponse(person.public())
    response.set_cookie(COOKIE, token, max_age=LIFETIME, path="/", secure=True, httponly=True, samesite="strict")
    return response


@router.get("/api/auth/me")
def me(request: Request):
    return request.state.principal.public()


@router.post("/api/auth/logout")
def logout(request: Request):
    request.app.state.auth.logout(request.state.principal.session)
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="strict")
    return response


@router.get("/api/admin/accounts")
def accounts(request: Request):
    admin(request)
    return {"items": request.app.state.auth.accounts()}


@router.post("/api/admin/accounts", status_code=201)
async def create(data: NewAccount, request: Request):
    admin(request)
    try:
        async with request.app.state.password_gate:
            await asyncio.to_thread(request.app.state.auth.create, data.username, data.password, data.rate_bps, data.max_playbacks)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    return {"ok": True}


@router.patch("/api/admin/accounts/{ident}")
def update(ident: int, data: AccountChange, request: Request):
    admin(request)
    fields = data.model_dump(exclude_unset=True)
    if any(fields.get(k) is None for k in ("enabled", "max_playbacks") if k in fields):
        raise HTTPException(422, "启用状态和同时播放上限不可为空")
    request.app.state.auth.update(ident, fields)
    return {"ok": True}


@router.post("/api/admin/accounts/{ident}/password")
async def reset(ident: int, data: PasswordChange, request: Request):
    admin(request)
    async with request.app.state.password_gate:
        encoded = await asyncio.to_thread(password_hash, data.password)
    request.app.state.auth.update(ident, {"password": encoded})
    return {"ok": True}
