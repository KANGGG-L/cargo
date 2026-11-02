"""Database initialization script for HKG Cargo Control Tower.

Idempotently initializes data/control_tower.sqlite from models.py
and bulk-loads CSV datasets from data/public/ and data/synthetic/.
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/

from sqlalchemy import text

from app.config import get_settings
from app.db import engine
from app.models import Base

settings = get_settings()
ROOT_DIR = Path(__file__).resolve().parents[2]
PUBLIC_DIR = ROOT_DIR / "data" / "public"
SYNTHETIC_DIR = ROOT_DIR / "data" / "synthetic"


def load_csv_rows(file_path):
    rows = []
    with open(file_path, "r", encoding="utf-8") as f:
        # Filter out comments starting with '#'
        lines = [line for line in f if not line.startswith("#")]
        reader = csv.DictReader(lines)
        for r in reader:
            rows.append(r)
    return rows


def clean_row_for_table(table_name, row):
    cleaned = dict(row)
    # Convert numerical strings to float/int where appropriate
    for k, v in cleaned.items():
        if v == "" or v is None:
            cleaned[k] = None
        else:
            try:
                if "." in v:
                    cleaned[k] = float(v)
                else:
                    # check if integer or string
                    try:
                        cleaned[k] = int(v)
                    except ValueError:
                        cleaned[k] = v
            except ValueError:
                cleaned[k] = v
    return cleaned


def init_database():
    print(f"[INFO] Initializing SQLite database at: {settings.db_path}")
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)

    # Re-create all tables
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    print("[OK] Re-created all star-schema tables from ORM metadata.")

    table_file_mapping = [
        # Public macro
        ("public_hkg_air_cargo_monthly", PUBLIC_DIR / "hkg_air_cargo_monthly.csv"),
        ("public_scfi_ocean_rate_weekly", PUBLIC_DIR / "scfi_ocean_rate_weekly.csv"),
        # Synthetic operational
        ("dim_customers", SYNTHETIC_DIR / "dim_customers.csv"),
        ("dim_shipments", SYNTHETIC_DIR / "dim_shipments.csv"),
        ("fact_shipment_legs", SYNTHETIC_DIR / "fact_shipment_legs.csv"),
        ("fact_air_kpi_daily", SYNTHETIC_DIR / "fact_air_kpi_daily.csv"),
        ("fact_ocean_rate_weekly", SYNTHETIC_DIR / "fact_ocean_rate_weekly.csv"),
        ("fact_sea_kpi_weekly", SYNTHETIC_DIR / "fact_sea_kpi_weekly.csv"),
        ("fact_truck_kpi_daily", SYNTHETIC_DIR / "fact_truck_kpi_daily.csv"),
        ("fact_rate_cards", SYNTHETIC_DIR / "fact_rate_cards.csv"),
        ("fact_disruption_events", SYNTHETIC_DIR / "fact_disruption_events.csv"),
        ("dim_milestone_codes", SYNTHETIC_DIR / "dim_milestone_codes.csv"),
        ("dim_locations", SYNTHETIC_DIR / "dim_locations.csv"),
        ("fact_alert_rules", SYNTHETIC_DIR / "fact_alert_rules.csv"),
        ("fact_milestones_plan", SYNTHETIC_DIR / "fact_milestones_plan.csv"),
        ("fact_milestone_events", SYNTHETIC_DIR / "fact_milestone_events.csv"),
    ]

    with engine.begin() as conn:
        for table_name, csv_path in table_file_mapping:
            if not csv_path.exists():
                print(f"[WARN] File not found: {csv_path}, skipping table {table_name}")
                continue

            raw_rows = load_csv_rows(csv_path)
            if not raw_rows:
                print(f"[WARN] No data in {csv_path}")
                continue

            cleaned_rows = [clean_row_for_table(table_name, r) for r in raw_rows]
            cols = list(cleaned_rows[0].keys())
            col_list_str = ", ".join(cols)
            val_placeholders = ", ".join([f":{c}" for c in cols])
            insert_sql = text(f"INSERT INTO {table_name} ({col_list_str}) VALUES ({val_placeholders})")

            conn.execute(insert_sql, cleaned_rows)
            print(f"[OK] Ingested {len(cleaned_rows)} rows into {table_name}")

    # Verify counts
    with engine.connect() as conn:
        print("[INFO] Row count verification:")
        for table_name, _ in table_file_mapping:
            res = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar()
            print(f"  - {table_name}: {res} rows")

    print("[OK] Database initialization and ingestion completed successfully.")


if __name__ == "__main__":
    init_database()
