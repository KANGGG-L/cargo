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
