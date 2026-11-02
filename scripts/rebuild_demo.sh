#!/usr/bin/env bash
# Rebuild the DEMO database to pristine state (idempotent, deterministic).
# Run this the day before an interview so every demo highlight replays.
set -euo pipefail
cd "$(dirname "$0")/../backend"
PY="${PYTHON:-python3}"
[ -x .venv/bin/python ] && PY="$(pwd)/.venv/bin/python"
"$PY" scripts/generate_data.py          # seed=42, byte-reproducible
"$PY" scripts/init_db.py                # CSVs -> sqlite + demo users + ops clock
"$PY" - <<'PY'
import sqlite3
from app.milestones.rules import sync
conn = sqlite3.connect("../data/control_tower.sqlite")
r = sync(conn)
print("rule sync:", r["created"], "created /", r["open_total"], "open")
conn.close()
PY
echo "Demo database rebuilt. Start servers and follow docs/DEMO_SCRIPT.md."
