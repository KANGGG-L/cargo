"""Star-schema ORM models for the HKG Cargo Control Tower.

Every operational fact is stored per *leg* with a `transport_mode` column
(SEA/TRUCK/AIR) rather than per vertical: the same schema backs air-freight,
ocean-freight and road-freight narratives — the application layer picks which
mode to highlight. Timestamps are stored as ISO-8601 strings, which SQLite
compares lexicographically and accepts in julianday()/strftime() expressions.
"""

from sqlalchemy import Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------- Dimension Tables


class Customer(Base):
    __tablename__ = "dim_customers"

    customer_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    customer_name: Mapped[str] = mapped_column(String(80))
    industry_segment: Mapped[str] = mapped_column(String(30))
    region: Mapped[str] = mapped_column(String(30))
    tier: Mapped[str] = mapped_column(String(20))
    payment_terms: Mapped[str] = mapped_column(String(20))


class Shipment(Base):
    __tablename__ = "dim_shipments"

    shipment_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(20), ForeignKey("dim_customers.customer_id"))
    origin_location: Mapped[str] = mapped_column(String(10))
    destination_location: Mapped[str] = mapped_column(String(10))
    transport_chain_type: Mapped[str] = mapped_column(String(30))
    cargo_category: Mapped[str] = mapped_column(String(30))
    total_chargeable_weight_kg: Mapped[float] = mapped_column(Float)
    total_volume_cbm: Mapped[float] = mapped_column(Float)
    total_pieces: Mapped[int] = mapped_column(Integer)
    booking_ts: Mapped[str] = mapped_column(String(30))
    contracted_revenue_usd: Mapped[float] = mapped_column(Float)
    estimated_cost_usd: Mapped[float] = mapped_column(Float)
    actual_cost_usd: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20))

    __table_args__ = (
        Index("ix_shipments_customer_id", "customer_id"),
        Index("ix_shipments_chain_type", "transport_chain_type"),
    )


# ---------------------------------------------------------------- Fact Tables


class ShipmentLeg(Base):
    __tablename__ = "fact_shipment_legs"

    leg_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    shipment_id: Mapped[str] = mapped_column(String(30), ForeignKey("dim_shipments.shipment_id"))
    leg_sequence: Mapped[int] = mapped_column(Integer)
    transport_mode: Mapped[str] = mapped_column(String(10))
    origin_facility: Mapped[str] = mapped_column(String(10))
    destination_facility: Mapped[str] = mapped_column(String(10))
    carrier_code: Mapped[str] = mapped_column(String(40))
    voyage_flight_no: Mapped[str] = mapped_column(String(30))
    planned_depart_ts: Mapped[str] = mapped_column(String(30))
    actual_depart_ts: Mapped[str] = mapped_column(String(30))
    planned_arrive_ts: Mapped[str] = mapped_column(String(30))
    actual_arrive_ts: Mapped[str] = mapped_column(String(30))
    delay_minutes: Mapped[float] = mapped_column(Float)
    distance_km: Mapped[float] = mapped_column(Float)
    allocated_cost_usd: Mapped[float] = mapped_column(Float)
    leg_status: Mapped[str] = mapped_column(String(20))

    __table_args__ = (
        Index("ix_legs_shipment_id", "shipment_id"),
        Index("ix_legs_mode_planned_depart", "transport_mode", "planned_depart_ts"),
        Index("ix_legs_origin_dest", "origin_facility", "destination_facility"),
    )


class AirKpiDaily(Base):
    __tablename__ = "fact_air_kpi_daily"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_date: Mapped[str] = mapped_column(String(10))
    route_lane: Mapped[str] = mapped_column(String(20))
    scheduled_flights: Mapped[int] = mapped_column(Integer)
    completed_flights: Mapped[int] = mapped_column(Integer)
    cancelled_flights: Mapped[int] = mapped_column(Integer)
    atk_thousand: Mapped[float] = mapped_column(Float)
    rtk_thousand: Mapped[float] = mapped_column(Float)
    cargo_load_factor: Mapped[float] = mapped_column(Float)
    on_time_departure_rate: Mapped[float] = mapped_column(Float)
    on_time_arrival_rate: Mapped[float] = mapped_column(Float)
    cargo_yield_per_rtk_usd: Mapped[float] = mapped_column(Float)
    backlog_tonnes: Mapped[float] = mapped_column(Float)

    __table_args__ = (
        Index("ix_airkpi_lane_date", "route_lane", "report_date"),
    )


class OceanRateWeekly(Base):
    __tablename__ = "fact_ocean_rate_weekly"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    week_start_date: Mapped[str] = mapped_column(String(10))
    feeder_corridor: Mapped[str] = mapped_column(String(30))
    average_rate_per_feu_usd: Mapped[float] = mapped_column(Float)
    fuel_surcharge_baf: Mapped[float] = mapped_column(Float)
    terminal_handling_charge_usd: Mapped[float] = mapped_column(Float)

    __table_args__ = (
        Index("ix_ocean_corridor_date", "feeder_corridor", "week_start_date"),
    )


class SeaKpiWeekly(Base):
    """Weekly feeder-barge performance per corridor — sea's counterpart to the
    air lane daily KPI, so ocean operations get first-class metrics too."""

    __tablename__ = "fact_sea_kpi_weekly"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    week_start_date: Mapped[str] = mapped_column(String(10))
    feeder_corridor: Mapped[str] = mapped_column(String(30))
    scheduled_sailings: Mapped[int] = mapped_column(Integer)
    completed_sailings: Mapped[int] = mapped_column(Integer)
    cancelled_sailings: Mapped[int] = mapped_column(Integer)
    on_time_departure_rate: Mapped[float] = mapped_column(Float)  # dep within 240 min
    avg_transit_hours: Mapped[float] = mapped_column(Float)
    slot_utilization: Mapped[float] = mapped_column(Float)  # 0-1
    backlog_teu: Mapped[float] = mapped_column(Float)

    __table_args__ = (
        Index("ix_seakpi_corridor_week", "feeder_corridor", "week_start_date"),
    )


class TruckKpiDaily(Base):
    """Daily cross-border truck performance per GBA checkpoint — the road
    counterpart of the air lane KPI (Shenzhen Bay / Huanggang / Wenjindu)."""

    __tablename__ = "fact_truck_kpi_daily"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_date: Mapped[str] = mapped_column(String(10))
    checkpoint: Mapped[str] = mapped_column(String(12))  # SZBP | HGA | WJD
    scheduled_trips: Mapped[int] = mapped_column(Integer)
    completed_trips: Mapped[int] = mapped_column(Integer)
    cancelled_trips: Mapped[int] = mapped_column(Integer)
    on_time_arrival_rate: Mapped[float] = mapped_column(Float)  # within 60 min
    avg_crossing_minutes: Mapped[float] = mapped_column(Float)
    queue_backlog_trucks: Mapped[float] = mapped_column(Float)
    avg_cost_per_tonne_usd: Mapped[float] = mapped_column(Float)

    __table_args__ = (
        Index("ix_truckkpi_checkpoint_date", "checkpoint", "report_date"),
    )


class RateCard(Base):
    __tablename__ = "fact_rate_cards"

    rate_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    transport_mode: Mapped[str] = mapped_column(String(10))
    origin_zone: Mapped[str] = mapped_column(String(20))
    dest_zone: Mapped[str] = mapped_column(String(20))
    weight_break: Mapped[str] = mapped_column(String(20))
    base_rate_usd: Mapped[float] = mapped_column(Float)
    effective_start_date: Mapped[str] = mapped_column(String(10))
    effective_end_date: Mapped[str] = mapped_column(String(10))


class DisruptionEvent(Base):
    __tablename__ = "fact_disruption_events"

    event_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    event_code: Mapped[str] = mapped_column(String(40))
    event_category: Mapped[str] = mapped_column(String(40))
    affected_mode: Mapped[str] = mapped_column(String(20))
    start_timestamp: Mapped[str] = mapped_column(String(30))
    end_timestamp: Mapped[str] = mapped_column(String(30))
    primary_location: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(String(255))
    target_metric_impact: Mapped[str] = mapped_column(String(255))


# ---------------------------------------------------------------- Public Macro Tables


class PublicHkgAirCargoMonthly(Base):
    __tablename__ = "public_hkg_air_cargo_monthly"

    year_month: Mapped[str] = mapped_column(String(7), primary_key=True)
    cargo_tonnage_total: Mapped[float] = mapped_column(Float)
    cargo_tonnage_inbound: Mapped[float] = mapped_column(Float)
    cargo_tonnage_outbound: Mapped[float] = mapped_column(Float)
    cargo_tonnage_transshipment: Mapped[float] = mapped_column(Float)
    yoy_growth_rate: Mapped[float] = mapped_column(Float)
    mom_growth_rate: Mapped[float] = mapped_column(Float)
    data_source: Mapped[str] = mapped_column(String(50))


class PublicScfiOceanRateWeekly(Base):
    __tablename__ = "public_scfi_ocean_rate_weekly"

    week_date: Mapped[str] = mapped_column(String(10), primary_key=True)
    composite_index: Mapped[float] = mapped_column(Float)
    shanghai_europe_usd_teu: Mapped[float] = mapped_column(Float)
    shanghai_med_usd_teu: Mapped[float] = mapped_column(Float)
    shanghai_uswc_usd_feu: Mapped[float] = mapped_column(Float)
    shanghai_usec_usd_feu: Mapped[float] = mapped_column(Float)
    shanghai_seasia_usd_teu: Mapped[float] = mapped_column(Float)
    data_source: Mapped[str] = mapped_column(String(50))


# ---------------------------------------------------------------- milestones & alerts (F1)


class MilestoneCode(Base):
    """Cargo-iQ-style milestone dictionary across all three modes."""

    __tablename__ = "dim_milestone_codes"

    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str] = mapped_column(String(40))
    mode: Mapped[str] = mapped_column(String(10))  # SHIPMENT | SEA | AIR | TRUCK
    seq_group: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(200))


class MilestonePlan(Base):
    """Planned milestone timestamps — the schedule baseline alerts are measured against."""

    __tablename__ = "fact_milestones_plan"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shipment_id: Mapped[str] = mapped_column(String(30), index=True)
    leg_id: Mapped[str | None] = mapped_column(String(24), nullable=True)  # null = shipment level
    code: Mapped[str] = mapped_column(String(8))
    planned_ts: Mapped[str] = mapped_column(String(30))

    __table_args__ = (Index("ix_mplan_shipment", "shipment_id", "code"),)


class MilestoneEvent(Base):
    """Actually reported milestone events (generator, FSU ingest, or agent)."""

    __tablename__ = "fact_milestone_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shipment_id: Mapped[str] = mapped_column(String(30), index=True)
    leg_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
    code: Mapped[str] = mapped_column(String(8))
    event_ts: Mapped[str] = mapped_column(String(30))
    source: Mapped[str] = mapped_column(String(12))  # generator | fsu | agent
    dedupe_key: Mapped[str] = mapped_column(String(64), unique=True)

    __table_args__ = (Index("ix_mevent_shipment", "shipment_id", "code"),)


class AlertRule(Base):
    __tablename__ = "fact_alert_rules"

    rule_id: Mapped[str] = mapped_column(String(12), primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    rule_type: Mapped[str] = mapped_column(String(20))  # missing_event | delay_over
    code: Mapped[str] = mapped_column(String(8))  # milestone code the rule watches
    threshold_minutes: Mapped[int] = mapped_column(Integer)
    severity: Mapped[str] = mapped_column(String(10))  # info | medium | high


class Alert(Base):
    """Exception tickets produced by the rule engine, the agent, or ingest."""

    __tablename__ = "fact_alerts"

    alert_id: Mapped[str] = mapped_column(String(16), primary_key=True)  # AL-000001
    shipment_id: Mapped[str] = mapped_column(String(30), index=True)
    rule_id: Mapped[str | None] = mapped_column(String(12), nullable=True)
    source: Mapped[str] = mapped_column(String(10))  # rules | agent | ingest
    severity: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(String(120))
    detail: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(12))  # OPEN | ACKNOWLEDGED | RESOLVED | CLOSED
    created_ts: Mapped[str] = mapped_column(String(30))
    updated_ts: Mapped[str] = mapped_column(String(30))
    assignee: Mapped[str | None] = mapped_column(String(40), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(String(500), nullable=True)


# ---------------------------------------------------------------- ingest (F4)


class IngestLog(Base):
    __tablename__ = "ingest_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_name: Mapped[str] = mapped_column(String(60))
    raw_chars: Mapped[int] = mapped_column(Integer)
    parsed: Mapped[int] = mapped_column(Integer)
    ingested: Mapped[int] = mapped_column(Integer)
    duplicates: Mapped[int] = mapped_column(Integer)
    rejected: Mapped[int] = mapped_column(Integer)
    processed_ts: Mapped[str] = mapped_column(String(30))


class IngestReject(Base):
    __tablename__ = "ingest_rejects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ingest_id: Mapped[int] = mapped_column(Integer, index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(120))
    raw_line: Mapped[str] = mapped_column(String(200))


# ---------------------------------------------------------------- notifications (F3)


class Subscription(Base):
    """Milestone/alert subscription (Cathay Track & Trace style)."""

    __tablename__ = "dim_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subscriber_email: Mapped[str] = mapped_column(String(120))
    shipment_id: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    # NULL shipment_id = global subscription (all high-severity alerts)
    notify_on: Mapped[str] = mapped_column(String(60))  # csv: ALERT,DELAY,MISSING
    delay_threshold_min: Mapped[int] = mapped_column(Integer)
    channel: Mapped[str] = mapped_column(String(10))  # email | webhook
    created_ts: Mapped[str] = mapped_column(String(30))

    # never reuse rowids: outbox rows reference deleted subscriptions by id
    __table_args__ = {"sqlite_autoincrement": True}


class NotificationOutbox(Base):
    """Transactional outbox — rows are enqueued on events and marked sent by the
    dispatch worker (SMTP optional; the ledger is the proof of delivery intent)."""

    __tablename__ = "notification_outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subscription_id: Mapped[int] = mapped_column(Integer, index=True)
    event_type: Mapped[str] = mapped_column(String(20))  # ALERT | DELAY | MISSING
    shipment_id: Mapped[str] = mapped_column(String(30))
    subject: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(String(800))
    channel: Mapped[str] = mapped_column(String(10))
    created_ts: Mapped[str] = mapped_column(String(30))
    sent_ts: Mapped[str | None] = mapped_column(String(30), nullable=True)

    __table_args__ = {"sqlite_autoincrement": True}


# ---------------------------------------------------------------- map (F2)


class Location(Base):
    """Facility coordinates for the map view (ports / airports / checkpoints)."""

    __tablename__ = "dim_locations"

    code: Mapped[str] = mapped_column(String(12), primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    kind: Mapped[str] = mapped_column(String(12))  # seaport | airport | checkpoint
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)


# ---------------------------------------------------------------- orders (F5)


class OrderLifecycle(Base):
    """Event-sourced order lifecycle (DRAFT→QUOTED→BOOKED→IN_PROGRESS→COMPLETED/CANCELLED)."""

    __tablename__ = "fact_order_lifecycle"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shipment_id: Mapped[str] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(14))
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    ts: Mapped[str] = mapped_column(String(30))

    __table_args__ = {"sqlite_autoincrement": True}


class AirWaybill(Base):
    __tablename__ = "dim_awb"

    awb_no: Mapped[str] = mapped_column(String(16), primary_key=True)  # 160-12345675
    shipment_id: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    airline_code: Mapped[str] = mapped_column(String(4))
    created_ts: Mapped[str] = mapped_column(String(30))


# ---------------------------------------------------------------- documents (F7)


class Document(Base):
    __tablename__ = "dim_documents"

    doc_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    shipment_id: Mapped[str] = mapped_column(String(30), index=True)
    doc_type: Mapped[str] = mapped_column(String(16))  # AWB | DG_DECL | PACKING_LIST | CUSTOMS | INVOICE
    file_path: Mapped[str] = mapped_column(String(200))
    eawb_status: Mapped[str] = mapped_column(String(10))  # none | sent | accepted
    created_ts: Mapped[str] = mapped_column(String(30))

    # never reuse doc ids on delete
    __table_args__ = {"sqlite_autoincrement": True}


# ---------------------------------------------------------------- settlement (F8)


class ChargeLine(Base):
    __tablename__ = "fact_charge_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shipment_id: Mapped[str] = mapped_column(String(30), index=True)
    charge_type: Mapped[str] = mapped_column(String(16))  # freight | fuel | thc | demurrage | uld
    amount_usd: Mapped[float] = mapped_column(Float)
    basis: Mapped[str] = mapped_column(String(120))
    created_ts: Mapped[str] = mapped_column(String(30))

    __table_args__ = {"sqlite_autoincrement": True}


class Invoice(Base):
    __tablename__ = "fact_invoices"

    invoice_id: Mapped[str] = mapped_column(String(16), primary_key=True)  # IN-000001
    customer_id: Mapped[str] = mapped_column(String(20), index=True)
    shipment_id: Mapped[str] = mapped_column(String(30), index=True)
    amount_usd: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(10))  # open | paid | disputed
    created_ts: Mapped[str] = mapped_column(String(30))
    paid_ts: Mapped[str | None] = mapped_column(String(30), nullable=True)

    __table_args__ = {"sqlite_autoincrement": True}


# ---------------------------------------------------------------- portal (F6)


class User(Base):
    __tablename__ = "dim_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(120), unique=True)
    password_hash: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(10))  # ops | manager | customer
    customer_id: Mapped[str | None] = mapped_column(String(20), nullable=True)  # scope for customer role
    created_ts: Mapped[str] = mapped_column(String(30))

    __table_args__ = {"sqlite_autoincrement": True}


# ---------------------------------------------------------------- planned legs & ETA (V1.0-B)


class PlannedLeg(Base):
    """Booked-but-not-operated legs — the plan the ETA model predicts against."""

    __tablename__ = "fact_planned_legs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shipment_id: Mapped[str] = mapped_column(String(30), index=True)
    leg_sequence: Mapped[int] = mapped_column(Integer)
    transport_mode: Mapped[str] = mapped_column(String(10))
    origin_facility: Mapped[str] = mapped_column(String(10))
    destination_facility: Mapped[str] = mapped_column(String(10))
    carrier_code: Mapped[str] = mapped_column(String(40))
    planned_depart_ts: Mapped[str] = mapped_column(String(30))
    planned_arrive_ts: Mapped[str] = mapped_column(String(30))
    basis: Mapped[str] = mapped_column(String(80))  # which schedule template built it

    __table_args__ = {"sqlite_autoincrement": True}
