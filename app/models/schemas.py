"""对外 API 的 Pydantic 模型。"""
from __future__ import annotations

from pydantic import BaseModel


class LoginPayload(BaseModel):
    username: str = ""
    password: str = ""


class LoginResponse(BaseModel):
    ok: bool
    token: str = ""