"""F6 portal: session auth + role-scoped views (lean, cookie-based).

ops/manager see the full network; customer accounts are row-level scoped to
their own shipments. Auth guards the portal endpoints only — the existing
ops pages keep working (single-tenant workbench).
"""

import hashlib
import hmac
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.config import get_settings

router = APIRouter(prefix="/api/portal", tags=["portal"])

COOKIE = "hkg_session"
_SECRET = "hkg-ct-demo-secret"  # portfolio demo; production would use a signed JWT


def _conn():
    conn = sqlite3.connect(get_settings().db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _token(email: str, password_hash: str) -> str:
    return hmac.new(_SECRET.encode(), f"{email}|{password_hash}".encode(), hashlib.sha256).hexdigest()


class LoginRequest(BaseModel):
    email: str = Field(max_length=120)
    password: str = Field(max_length=80)


@router.post("/login")
def login(req: LoginRequest, response: Response):
    conn = _conn()
    try:
        user = conn.execute(
            "SELECT email, password_hash, role, customer_id FROM dim_users WHERE email = ?",
            (req.email,),
        ).fetchone()
    finally:
        conn.close()
    if not user or not hmac.compare_digest(user["password_hash"], hashlib.sha256(req.password.encode()).hexdigest()):
        raise HTTPException(status_code=401, detail="invalid credentials")
    response.set_cookie(COOKIE, _token(user["email"], user["password_hash"]), httponly=True)
    return {"email": user["email"], "role": user["role"], "customer_id": user["customer_id"]}


def _require_user(request: Request) -> dict:
    token = request.cookies.get(COOKIE, "")
    if not token:
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


@router.get("/me")
def me(request: Request):
    return _require_user(request)


@router.get("/shipments")
def portal_shipments(request: Request):
    """Role-scoped shipment list: customer accounts see only their own."""
    user = _require_user(request)
    conn = _conn()
    try:
        if user["role"] == "customer":
            rows = conn.execute(
                """
                SELECT s.shipment_id, s.origin_location, s.destination_location, s.status,
                       s.transport_chain_type, s.total_chargeable_weight_kg,
                       s.contracted_revenue_usd, s.booking_ts
                FROM dim_shipments s WHERE s.customer_id = ?
                ORDER BY s.booking_ts DESC LIMIT 100
                """,
                (user["customer_id"],),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT s.shipment_id, s.origin_location, s.destination_location, s.status,
                       s.transport_chain_type, s.total_chargeable_weight_kg,
                       s.contracted_revenue_usd, s.booking_ts
                FROM dim_shipments s ORDER BY s.booking_ts DESC LIMIT 100
                """
            ).fetchall()
    finally:
        conn.close()
    return {"viewer": {"email": user["email"], "role": user["role"]}, "shipments": [dict(r) for r in rows]}
