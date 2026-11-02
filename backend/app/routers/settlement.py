"""F8 settlement: charge lines from deterministic rules, invoice lifecycle."""

import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import require_session
from app.config import get_settings

router = APIRouter(
    prefix="/api/settlement",
    dependencies=[Depends(require_session)],
    tags=["settlement"])

FUEL_RATE = 0.12
THC_FLAT_USD = 180.0
DEMURRAGE_USD_PER_TEU_DAY = 35.0
DEMURRAGE_FREE_DAYS = 1
DEMURRAGE_CAP_USD = 500.0
CBM_PER_TEU = 67.0


def _conn():
    conn = sqlite3.connect(get_settings().db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _compute_charge_lines(conn, shipment_id: str) -> list[dict]:
    shipment = conn.execute(
        "SELECT total_chargeable_weight_kg, contracted_revenue_usd FROM dim_shipments WHERE shipment_id = ?",
        (shipment_id,),
    ).fetchone()
    if not shipment:
        raise HTTPException(status_code=404, detail="shipment not found")

    legs = conn.execute(
        "SELECT allocated_cost_usd FROM fact_shipment_legs WHERE shipment_id = ?",
        (shipment_id,),
    ).fetchall()
    weight = shipment["total_chargeable_weight_kg"] or 0.0
    if legs:
        freight = sum(l["allocated_cost_usd"] for l in legs)
        basis = f"sum of {len(legs)} allocated leg costs"
    else:
        freight = shipment["contracted_revenue_usd"] * 0.8
        basis = "80% of contracted revenue (pre-operation estimate)"

    lines = [
        {"charge_type": "freight", "amount_usd": round(freight, 2), "basis": basis},
        {"charge_type": "fuel", "amount_usd": round(freight * FUEL_RATE, 2), "basis": f"{FUEL_RATE:.0%} of freight (BAF)"},
        {"charge_type": "thc", "amount_usd": THC_FLAT_USD, "basis": "terminal handling charge, flat"},
    ]

    # demurrage: TEU-days beyond the free period on the final delivery leg
    final = conn.execute(
        """
        SELECT l.delay_minutes, s.total_volume_cbm
        FROM fact_shipment_legs l JOIN dim_shipments s ON s.shipment_id = l.shipment_id
        WHERE l.shipment_id = ? ORDER BY l.leg_sequence DESC LIMIT 1
        """,
        (shipment_id,),
    ).fetchone()
    if final and final["delay_minutes"] and final["delay_minutes"] > DEMURRAGE_FREE_DAYS * 1440:
        days_over = (final["delay_minutes"] / 1440.0) - DEMURRAGE_FREE_DAYS
        teu = max((final["total_volume_cbm"] or 0.0) / CBM_PER_TEU, 0.1)
        demurrage = min(
            DEMURRAGE_CAP_USD, round(days_over * teu * DEMURRAGE_USD_PER_TEU_DAY, 2)
        )
        lines.append({
            "charge_type": "demurrage",
            "amount_usd": demurrage,
            "basis": f"{days_over:.1f} d × {teu:.2f} TEU × ${DEMURRAGE_USD_PER_TEU_DAY}/TEU-day, capped ${DEMURRAGE_CAP_USD}",
        })
    return lines


@router.post("/{shipment_id}/charges")
def build_charges(shipment_id: str):
    conn = _conn()
    try:
        lines = _compute_charge_lines(conn, shipment_id)
        now = _now()
        conn.execute("DELETE FROM fact_charge_lines WHERE shipment_id = ?", (shipment_id,))
        conn.executemany(
            "INSERT INTO fact_charge_lines (shipment_id, charge_type, amount_usd, basis, created_ts)"
            " VALUES (?, ?, ?, ?, ?)",
            [(shipment_id, l["charge_type"], l["amount_usd"], l["basis"], now) for l in lines],
        )
        conn.commit()
        total = round(sum(l["amount_usd"] for l in lines), 2)
        return {"shipment_id": shipment_id, "lines": lines, "total_usd": total}
    finally:
        conn.close()


@router.get("/{shipment_id}")
def settlement_view(shipment_id: str):
    conn = _conn()
    try:
        lines = [
            dict(r)
            for r in conn.execute(
                "SELECT charge_type, amount_usd, basis, created_ts FROM fact_charge_lines"
                " WHERE shipment_id = ? ORDER BY id",
                (shipment_id,),
            ).fetchall()
        ]
        invoice = conn.execute(
            "SELECT * FROM fact_invoices WHERE shipment_id = ?", (shipment_id,)
        ).fetchone()
        return {
            "shipment_id": shipment_id,
            "lines": lines,
            "total_usd": round(sum(l["amount_usd"] for l in lines), 2),
            "invoice": dict(invoice) if invoice else None,
        }
    finally:
        conn.close()


class InvoiceRequest(BaseModel):
    model_config = {"protected_namespaces": ()}


@router.post("/{shipment_id}/invoice")
def create_invoice(shipment_id: str, req: InvoiceRequest = None):
    conn = _conn()
    try:
        shipment = conn.execute(
            "SELECT customer_id FROM dim_shipments WHERE shipment_id = ?", (shipment_id,)
        ).fetchone()
        if not shipment:
            raise HTTPException(status_code=404, detail="shipment not found")
        if conn.execute("SELECT 1 FROM fact_invoices WHERE shipment_id = ?", (shipment_id,)).fetchone():
            raise HTTPException(status_code=409, detail="invoice already exists")
        lines = _compute_charge_lines(conn, shipment_id)
        total = round(sum(l["amount_usd"] for l in lines), 2)
        n = int((conn.execute("SELECT MAX(invoice_id) FROM fact_invoices").fetchone()[0] or "IN-000000").split("-")[1]) + 1
        invoice_id = f"IN-{n:06d}"
        conn.execute(
            "INSERT INTO fact_invoices (invoice_id, customer_id, shipment_id, amount_usd, status, created_ts)"
            " VALUES (?, ?, ?, ?, 'open', ?)",
            (invoice_id, shipment["customer_id"], shipment_id, total, _now()),
        )
        conn.executemany(
            "INSERT INTO fact_charge_lines (shipment_id, charge_type, amount_usd, basis, created_ts)"
            " VALUES (?, ?, ?, ?, ?)",
            [(shipment_id, l["charge_type"], l["amount_usd"], l["basis"], _now()) for l in lines],
        )
        conn.commit()
        return {"invoice_id": invoice_id, "amount_usd": total, "status": "open"}
    finally:
        conn.close()


@router.post("/invoice/{invoice_id}/dispute")
def dispute_invoice(invoice_id: str):
    conn = _conn()
    try:
        row = conn.execute("SELECT status FROM fact_invoices WHERE invoice_id = ?", (invoice_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="invoice not found")
        if row["status"] != "open":
            raise HTTPException(status_code=409, detail=f"cannot dispute from status {row['status']}")
        conn.execute(
            "UPDATE fact_invoices SET status = 'disputed' WHERE invoice_id = ?", (invoice_id,)
        )
        conn.commit()
        return {"invoice_id": invoice_id, "status": "disputed"}
    finally:
        conn.close()


@router.post("/invoice/{invoice_id}/pay")
def pay_invoice(invoice_id: str):
    conn = _conn()
    try:
        row = conn.execute("SELECT status FROM fact_invoices WHERE invoice_id = ?", (invoice_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="invoice not found")
        if row["status"] == "paid":
            raise HTTPException(status_code=409, detail="already paid")
        if row["status"] not in ("open", "disputed"):
            raise HTTPException(status_code=409, detail=f"cannot pay from status {row['status']}")
        conn.execute(
            "UPDATE fact_invoices SET status = 'paid', paid_ts = ? WHERE invoice_id = ?",
            (_now(), invoice_id),
        )
        conn.commit()
        return {"invoice_id": invoice_id, "status": "paid"}
    finally:
        conn.close()
