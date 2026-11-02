#!/usr/bin/env bash
# Rebuild the DEMO database to pristine state (idempotent, deterministic).
# Run this the day before an interview so every demo highlight replays.
set -euo pipefail
cd "$(dirname "$0")/../backend"
python scripts/generate_data.py          # seed=42, byte-reproducible
python scripts/init_db.py                # CSVs -> sqlite + demo users + ops clock
python - <<'PY'
import sqlite3
from app.milestones.rules import sync
conn = sqlite3.connect("../data/control_tower.sqlite")
print("rule sync:", sync(conn))
conn.close()
PY
echo "Demo database rebuilt. Start servers and follow docs/DEMO_SCRIPT.md."
