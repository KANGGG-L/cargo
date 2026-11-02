"""FSU ingest endpoint + sample feed."""

from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.config import get_settings
from app.ingest.fsu import parse_and_ingest

router = APIRouter(prefix="/api/ingest", tags=["ingest"])

SAMPLE_PATH = get_settings().db_path.parents[1] / "data" / "samples" / "fsu_replay.txt"


class FsuRequest(BaseModel):
    text: str = Field(min_length=1, max_length=100_000)
    source_name: str = Field(default="manual", max_length=60)


@router.post("/fsu")
def ingest_fsu(req: FsuRequest):
    import sqlite3

    conn = sqlite3.connect(get_settings().db_path)
    conn.row_factory = sqlite3.Row
    try:
        result = parse_and_ingest(conn, req.text, req.source_name)
        return {
            "parsed": result.parsed,
            "ingested": result.ingested,
            "duplicates": result.duplicates,
            "rejected": result.rejected,
            "rejects": result.rejects,
            "auto_resolved_alerts": result.resolved_alerts,
        }
    finally:
        conn.close()


@router.get("/sample")
def sample_feed():
    if not SAMPLE_PATH.exists():
        return {"text": ""}
    return {"name": SAMPLE_PATH.name, "text": SAMPLE_PATH.read_text(encoding="utf-8")}
