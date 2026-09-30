"""内存 token 认证 + 登录失败限速。"""
from __future__ import annotations

import logging
import secrets
import threading
import time

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

TOKEN_TTL = 7 * 24 * 3600
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 300


class TokenStore:
    def __init__(self, ttl: int = TOKEN_TTL):
        self._tokens: dict[str, float] = {}
        self._lock = threading.Lock()
        self._ttl = ttl

    def _cleanup_locked(self) -> None:
        now = time.time()
        for k in [k for k, v in self._tokens.items() if v < now]:
            self._tokens.pop(k, None)

    def issue(self) -> str:
        with self._lock:
            self._cleanup_locked()
            token = secrets.token_urlsafe(32)
            self._tokens[token] = time.time() + self._ttl
            return token

    def check(self, token: str) -> bool:
        if not token:
            return False
        with self._lock:
            exp = self._tokens.get(token)
            if exp is None:
                return False
            if exp < time.time():
                self._tokens.pop(token, None)
                return False
            return True

    def revoke(self, token: str) -> None:
        if not token:
            return
        with self._lock:
            self._tokens.pop(token, None)


class LoginThrottle:
    def __init__(self, max_attempts: int = LOGIN_MAX_ATTEMPTS,
                 window: int = LOGIN_WINDOW_SECONDS):
        self._attempts: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self._max = max_attempts
        self._window = window

    def allow(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            bucket = [t for t in self._attempts.get(key, []) if now - t < self._window]
            self._attempts[key] = bucket
            return len(bucket) < self._max

    def record_failure(self, key: str) -> None:
        with self._lock:
            self._attempts.setdefault(key, []).append(time.time())

    def clear(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)


token_store = TokenStore()
login_throttle = LoginThrottle()


def client_key(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def require_auth(request: Request) -> None:
    token = request.headers.get("X-Auth-Token", "").strip()
    if not token_store.check(token):
        raise HTTPException(401, "未登录或登录已失效")