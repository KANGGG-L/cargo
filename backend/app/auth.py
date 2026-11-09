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


def _public_user(user: dict[str, Any]) -> dict[str, Any]:
    """Strip credential material before a user dict crosses the API boundary."""
    return {k: v for k, v in user.items() if k != "password_hash"}


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
    return _public_user(dict(user))


def token_for(user: dict[str, Any]) -> str:
    """Session token for a user dict; accepts raw rows and sanitized dicts alike."""
    if "password_hash" not in user:
        conn = _conn()
        try:
            row = conn.execute(
                "SELECT password_hash FROM dim_users WHERE email = ?", (user["email"],)
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            raise ValueError(f"unknown user {user['email']}")
        user = {**user, "password_hash": row[0]}
    return _token(user["email"], user["password_hash"])


def _resolve_token(token: str) -> dict[str, Any] | None:
    conn = _conn()
    try:
        for user in conn.execute(
            "SELECT email, password_hash, role, customer_id FROM dim_users"
        ).fetchall():
            if hmac.compare_digest(_token(user["email"], user["password_hash"]), token):
                return _public_user(dict(user))
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


def require_ops(request: Request) -> dict[str, Any]:
    """Workbench write endpoints are operator-only; customers are read-only."""
    user = require_session(request)
    if user.get("role") != "ops":
        raise HTTPException(status_code=403, detail="ops role required")
    return user


# R5-3 four-role capability model (minimal necessary). ops/manager may write;
# partner is a connected external party with full-network READ but no writes;
# customer is row-level scoped. This is a demo authz layer, not a real IdP.
ROLE_CAPABILITIES: dict[str, dict[str, bool]] = {
    "ops":      {"write": True,  "full_read": True},
    "manager":  {"write": True,  "full_read": True},
    "partner":  {"write": False, "full_read": True},
    "customer": {"write": False, "full_read": False},
}


def require_write(request: Request) -> dict[str, Any]:
    """Write endpoints: ops or manager. partner/customer are read-only."""
    user = require_session(request)
    if not ROLE_CAPABILITIES.get(user.get("role", ""), {}).get("write"):
        raise HTTPException(status_code=403, detail="write role required (ops/manager)")
    return user


def require_full_read(request: Request) -> dict[str, Any]:
    """Full-network read endpoints: ops/manager/partner (not row-scoped customer)."""
    user = require_session(request)
    if not ROLE_CAPABILITIES.get(user.get("role", ""), {}).get("full_read"):
        raise HTTPException(status_code=403, detail="full-network read role required")
    return user


def scoped_customer_id(user: dict[str, Any]) -> str | None:
    """Return the customer_id a query must be filtered by, or None for full-read
    roles (ops/manager/partner)."""
    if ROLE_CAPABILITIES.get(user.get("role", ""), {}).get("full_read"):
        return None
    return user.get("customer_id")


def require_shipment_access(request: Request, shipment_customer_id: str | None) -> dict[str, Any]:
    """Customer sessions may only touch shipments they own; ops/manager/partner
    see the whole network (full_read)."""
    user = require_session(request)
    if not ROLE_CAPABILITIES.get(user.get("role", ""), {}).get("full_read"):
        if shipment_customer_id != user.get("customer_id"):
            raise HTTPException(status_code=403, detail="shipment outside customer scope")
    return user
