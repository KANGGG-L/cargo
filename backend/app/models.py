"""Star-schema ORM models for the multimodal cargo control tower.

Design note: every operational fact is stored per *leg* with a `mode` column
(sea/truck/air) rather than per transportation vertical. The same schema backs
air-freight, ocean-freight and road-freight narratives — the application layer
picks which mode to highlight.
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------- dimensions


class Customer(Base):
    __tablename__ = "dim_customers"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    segment: Mapped[str] = mapped_column(String(20))  # forwarder | e_commerce | manufacturer
    region: Mapped[str] = mapped_column(String(30))  # Greater Bay | APAC | EMEA | Americas


class Shipment(Base):
    __tablename__ = "dim_shipments"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)  # SH-2025-00001
    customer_id: Mapped[str] = mapped_column(ForeignKey("dim_customers.id"))
    product_type: Mapped[str] = mapped_column(String(30))  # electronics | perishables | ...
    incoterm: Mapped[str] = mapped_column(String(3))  # FOB | CIF | EXW | DAP
    channel: Mapped[str] = mapped_column(String(20))  # direct | forwarder | e_platform
    priority: Mapped[str] = mapped_column(String(10))  # standard | express | critical
    origin_country: Mapped[str] = mapped_column(String(30))
    dest_country: Mapped[str] = mapped_column(String(30))
    created_ts: Mapped[datetime] = mapped_column(DateTime)


# ---------------------------------------------------------------- facts


class ShipmentLeg(Base):
    __tablename__ = "fact_shipment_legs"

    id: Mapped[str] = mapped_column(String(24), primary_key=True)  # LG-000001
    shipment_id: Mapped[str] = mapped_column(ForeignKey("dim_shipments.id"))
    leg_seq: Mapped[int] = mapped_column(Integer)  # 1..n within the shipment
    mode: Mapped[str] = mapped_column(String(5))  # sea | truck | air
    origin_code: Mapped[str] = mapped_column(String(5))  # UN/LOCODE or IATA: CNSHA, HKG, LAX
    dest_code: Mapped[str] = mapped_column(String(5))
    carrier: Mapped[str] = mapped_column(String(40))
    vehicle_ref: Mapped[str] = mapped_column(String(20))  # flight no / vessel name / truck id
    depart_ts: Mapped[datetime] = mapped_column(DateTime)
    planned_arrive_ts: Mapped[datetime] = mapped_column(DateTime)
    actual_arrive_ts: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delay_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight_tonnes: Mapped[float] = mapped_column(Float)
    volume_cbm: Mapped[float] = mapped_column(Float)
    revenue_usd: Mapped[float] = mapped_column(Float)
    cost_usd: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(12))  # planned | in_transit | delivered

    __table_args__ = (
        Index("ix_legs_mode_depart", "mode", "depart_ts"),
        Index("ix_legs_shipment", "shipment_id"),
    )


class AirKpiDaily(Base):
    __tablename__ = "fact_air_kpi_daily"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date)
    lane: Mapped[str] = mapped_column(String(10))  # HKG-LAX ...
    airline: Mapped[str] = mapped_column(String(40))
    flights: Mapped[int] = mapped_column(Integer)
    atk_million_tk: Mapped[float] = mapped_column(Float)  # available tonne-km (millions)
    borne_million_tk: Mapped[float] = mapped_column(Float)  # revenue tonne-km (millions)
    load_factor: Mapped[float] = mapped_column(Float)  # borne / available
    otp_pct: Mapped[float] = mapped_column(Float)  # on-time performance (+/-15 min)
    avg_delay_min: Mapped[float] = mapped_column(Float)
    yield_usd_per_tk: Mapped[float] = mapped_column(Float)

    __table_args__ = (Index("ix_airkpi_lane_date", "lane", "date"),)


class OceanRateWeekly(Base):
    __tablename__ = "fact_ocean_rate_weekly"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    week_start: Mapped[date] = mapped_column(Date)
    lane: Mapped[str] = mapped_column(String(20))  # e.g. CNSHA-HKG feeder, CNSHA-EURWB
    usd_per_feu: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(40))  # e.g. "SCFI (composite)" | "synthetic"


class DisruptionEvent(Base):
    __tablename__ = "fact_disruption_events"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(20))  # typhoon | port_congestion | strike | customs
    name: Mapped[str] = mapped_column(String(60))
    location_code: Mapped[str] = mapped_column(String(5))
    start_ts: Mapped[datetime] = mapped_column(DateTime)
    end_ts: Mapped[datetime] = mapped_column(DateTime)
    severity: Mapped[int] = mapped_column(Integer)  # 1 (minor) .. 5 (severe)
    affected_modes: Mapped[str] = mapped_column(String(20))  # csv: air,sea,truck
    notes: Mapped[str] = mapped_column(String(400))


class RateCard(Base):
    __tablename__ = "fact_rate_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product: Mapped[str] = mapped_column(String(20))  # air | sea | truck | sea_air
    origin_code: Mapped[str] = mapped_column(String(5))
    dest_code: Mapped[str] = mapped_column(String(5))
    weight_break: Mapped[str] = mapped_column(String(12))  # +0kg | +300kg | +1000kg | per_feu
    rate_usd: Mapped[float] = mapped_column(Float)  # per kg, or per FEU when weight_break=per_feu
    transit_days_min: Mapped[int] = mapped_column(Integer)
    transit_days_max: Mapped[int] = mapped_column(Integer)
    valid_until: Mapped[date] = mapped_column(Date)
