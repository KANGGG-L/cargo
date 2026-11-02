"""Session auth for data-bearing endpoints (F6/V1.0 hardening).

AUTH_ENABLED can be flipped off by the test suite (conftest) so the 67-test
body exercises business logic without login bookkeeping; a dedicated test
flips it back on to cover the 401/cookie paths.
"""

import hashlib
import hmac
import sqlite3
from typing import Any

from fastapi import HTTPException, Request

from app.config import get_settings

COOKIE = "hkg_session"
_SECRET = "hkg-ct-demo-secret"  # portfolio demo; production would use a signed JWT

AUTH_ENABLED = True


def _conn():
    conn = sqlite3.connect(get_settings().db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _token(email: str, password_hash: str) -> str:
    return hmac.new(
        _SECRET.encode(), f"{email}|{password_hash}".encode(), hashlib.sha256
    ).hexdigest()


def verify_login(email: str, password: str) -> dict[str, Any] | None:
    conn = _conn()
    try:
        user = conn.execute(
            "SELECT email, password_hash, role, customer_id FROM dim_users WHERE email = ?",
            (email,),
        ).fetchone()
    finally:
        conn.close()
    if not user or not hmac.compare_digest(
        user["password_hash"], hashlib.sha256(password.encode()).hexdigest()
    ):
        return None
    return dict(user)


def token_for(user: dict[str, Any]) -> str:
    return _token(user["email"], user["password_hash"])


def _resolve_token(token: str) -> dict[str, Any] | None:
    conn = _conn()
    try:
        for user in conn.execute(
            "SELECT email, password_hash, role, customer_id FROM dim_users"
        ).fetchall():
            if hmac.compare_digest(_token(user["email"], user["password_hash"]), token):
                return dict(user)
    finally:
        conn.close()
    return None


def require_session(request: Request) -> dict[str, Any]:
    token = request.cookies.get(COOKIE, "")
    if token:
        user = _resolve_token(token)
        if user:
            return user
        raise HTTPException(status_code=401, detail="invalid session")
    if not AUTH_ENABLED:
        # test/demo convenience: anonymous requests pass as ops, real cookies
        # still resolve their true identity (branch above)
        return {"email": "anonymous", "role": "ops", "customer_id": None}
    raise HTTPException(status_code=401, detail="not logged in")
    conn = _conn()
    try:
        for user in conn.execute(
            "SELECT email, password_hash, role, customer_id FROM dim_users"
        ).fetchall():
            if hmac.compare_digest(_token(user["email"], user["password_hash"]), token):
                return dict(user)
    finally:
        conn.close()
    raise HTTPException(status_code=401, detail="invalid session")
