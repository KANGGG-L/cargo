"""Document centre: generate and serve transport documents."""

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.config import get_settings
from app.documents import generator

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _conn():
    conn = sqlite3.connect(get_settings().db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _shipment(conn, shipment_id: str) -> dict:
    row = conn.execute(
        """
        SELECT s.*, c.customer_name FROM dim_shipments s
        JOIN dim_customers c ON c.customer_id = s.customer_id
        WHERE s.shipment_id = ?
        """,
        (shipment_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="shipment not found")
    return dict(row)


class GenerateRequest(BaseModel):
    doc_type: str = Field(pattern="^(AWB|DG_DECL|PACKING_LIST)$")


@router.post("/{shipment_id}/generate")
def generate_document(shipment_id: str, req: GenerateRequest):
    conn = _conn()
    try:
        shipment = _shipment(conn, shipment_id)
        awb = conn.execute(
            "SELECT awb_no, airline_code FROM dim_awb WHERE shipment_id = ?", (shipment_id,)
        ).fetchone()
        awb_dict = dict(awb) if awb else None
        if req.doc_type == "AWB" and not awb_dict:
            raise HTTPException(status_code=409, detail="allocate an AWB before generating the AWB document")

        if req.doc_type == "AWB":
            path = generator.generate_awb(shipment, awb_dict)
        elif req.doc_type == "DG_DECL":
            path = generator.generate_dg_decl(shipment)
        else:
            legs = [dict(r) for r in conn.execute(
                "SELECT leg_sequence, transport_mode, origin_facility, destination_facility, distance_km"
                " FROM fact_shipment_legs WHERE shipment_id = ? ORDER BY leg_sequence",
                (shipment_id,),
            ).fetchall()]
            path = generator.generate_packing_list(shipment, legs)

        n = int(conn.execute("SELECT COUNT(*) FROM dim_documents").fetchone()[0]) + 1
        doc_id = f"DOC-{n:04d}-{uuid.uuid4().hex[:4]}"
        eawb = "sent" if req.doc_type == "AWB" else "none"
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            "INSERT INTO dim_documents (doc_id, shipment_id, doc_type, file_path, eawb_status, created_ts)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (doc_id, shipment_id, req.doc_type, str(path), eawb, now),
        )
        conn.commit()
        return {"doc_id": doc_id, "doc_type": req.doc_type, "file": path.name, "eawb_status": eawb}
    finally:
        conn.close()


@router.get("/{shipment_id}")
def list_documents(shipment_id: str):
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT doc_id, doc_type, file_path, eawb_status, created_ts FROM dim_documents"
            " WHERE shipment_id = ? ORDER BY created_ts",
            (shipment_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/file/{doc_id}")
def download_document(doc_id: str):
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT file_path, doc_type FROM dim_documents WHERE doc_id = ?", (doc_id,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="document not found")
    path = Path(row["file_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="file missing")
    return FileResponse(path, media_type="application/pdf", filename=path.name)
