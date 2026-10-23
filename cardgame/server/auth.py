"""Username/password store.  The first login with a new name registers it;
the password may be empty.  Logins hand out tokens so a refreshed page can
reconnect without typing the password again."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from .storage import Storage

MAX_NAME = 16


class AuthError(Exception):
    pass


def _hash(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1).hex()


def check_username(name: object) -> str:
    if not isinstance(name, str):
        raise AuthError("用户名无效")
    name = name.strip()
    if not name:
        raise AuthError("请输入用户名")
    if len(name) > MAX_NAME:
        raise AuthError(f"用户名最长 {MAX_NAME} 个字符")
    if any(ch.isspace() and ch != " " or not ch.isprintable() for ch in name):
        raise AuthError("用户名含有非法字符")
    return name


class Users:
    def __init__(self, storage: Storage):
        self.storage = storage
        data = storage.load_json("users.json") or {}
        self.users: dict[str, dict] = data.get("users", {})
        self.tokens: dict[str, str] = data.get("tokens", {})

    def _save(self) -> None:
        self.storage.save_json("users.json", {"users": self.users, "tokens": self.tokens})

    def login(self, username: object, password: object) -> tuple[str, str, bool]:
        """Returns (username, token, registered_now)."""
        name = check_username(username)
        if not isinstance(password, str):
            password = ""
        rec = self.users.get(name)
        created = False
        if rec is None:
            salt = secrets.token_bytes(16)
            rec = self.users[name] = {"salt": salt.hex(), "hash": _hash(password, salt), "created": time.time()}
            created = True
        elif not hmac.compare_digest(rec["hash"], _hash(password, bytes.fromhex(rec["salt"]))):
            raise AuthError("密码错误")
        token = secrets.token_urlsafe(24)
        self.tokens[token] = name
        self._save()
        return name, token, created

    def resume(self, token: object) -> str:
        name = self.tokens.get(token) if isinstance(token, str) else None
        if name is None or name not in self.users:
            raise AuthError("登录已过期，请重新登录")
        return name

    def logout(self, token: object) -> None:
        if isinstance(token, str) and self.tokens.pop(token, None) is not None:
            self._save()
