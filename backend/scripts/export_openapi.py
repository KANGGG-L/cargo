"""Export the FastAPI OpenAPI schema to openapi.json (R5-5).

Run after changing routes:  python scripts/export_openapi.py
CI asserts the committed file matches the live schema (test_release5).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "openapi.json"


def export() -> dict:
    schema = app.openapi()
    OUT.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return schema


if __name__ == "__main__":
    schema = export()
    print(f"[OK] wrote {OUT} ({len(schema.get('paths', {}))} paths)")
