"""Deterministic Synthetic Operational Data Generator for HKG Cargo Control Tower.

Produces 7 CSV files into data/synthetic/ with fixed seed=42.
Embeds 3 deterministic anomaly scenarios:
1. Typhoon HKG hub closure (Sept 2025)
2. Yantian port congestion (March 2026)
3. Transpacific contract rate inversion (HKG-ORD, June 2026)
"""

import csv
from datetime import datetime, timedelta
from pathlib import Path
import random

# Fixed seed for strict determinism
RANDOM_SEED = 42
random.seed(RANDOM_SEED)

ROOT_DIR = Path(__file__).resolve().parents[2]
SYNTHETIC_DIR = ROOT_DIR / "data" / "synthetic"
SYNTHETIC_DIR.mkdir(parents=True, exist_ok=True)

START_DATE = datetime(2025, 5, 1, 0, 0, 0)
END_DATE = datetime(2026, 10, 31, 23, 59, 59)
TOTAL_DAYS = (END_DATE - START_DATE).days + 1

# Anomaly windows
TYPHOON_START = datetime(2025, 9, 15, 0, 0, 0)
TYPHOON_END = datetime(2025, 9, 21, 23, 59, 59)

YANTIAN_START = datetime(2026, 3, 1, 0, 0, 0)
YANTIAN_END = datetime(2026, 3, 15, 23, 59, 59)

ORD_ANOMALY_START = datetime(2026, 6, 1, 0, 0, 0)
ORD_ANOMALY_END = datetime(2026, 6, 30, 23, 59, 59)

# Land-side story: Shenzhen Bay checkpoint congestion (cross-border trucks)
TRUCK_START = datetime(2025, 11, 10, 0, 0, 0)
TRUCK_END = datetime(2025, 11, 24, 23, 59, 59)
TRUCK_CHECKPOINTS = ["SZBP", "HGA", "WJD"]


def generate_customers():
    customers = []
    segments = [
        "forwarder",
        "e_commerce",
        "manufacturer",
        "perishable_broker",
        "pharma_logistics",
    ]
    regions = ["Greater_Bay_Area", "APAC", "EMEA", "Americas"]
    tiers = ["Strategic", "Tier_1", "Tier_2"]
    terms = ["Net_30", "Net_60", "Prepaid"]

    # Fictional but plausible company names (de-sensitized demo data)
    names = [
        "Golden Dragon Logistics", "Pacific Bridge Forwarding", "Pearl River Express",
        "Silk Route Cargo", "Harbour Link Global", "Lotus Freight Systems",
        "Meridian Trade Lines", "Jade Gateway International", "Summit Cross-Border",
        "Azure Ocean Carriers", "Crimson Lane Logistics", "Delta Freight Works",
        "Evergreen Valley Cargo", "Fortune Star Shipping", "Grand Canal Forwarding",
        "Horizon Air Cargo Agency", "Imperial Dragon Trading", "Jetstream Consolidators",
        "Kite & Compass Logistics", "Lantern Bay Freight", "Mountain Pass Shipping",
        "Neon Harbour Express", "Orient Crown Logistics", "Phoenix Wing Cargo",
        "Quantum Freight Solutions", "Red Pine Trading", "Southern Cross Cargo",
        "Tiger Gate Logistics", "Unity Freight Network", "Victory Anchor Shipping",
        "West Wind Express", "Xi'an Silk Road Cargo", "Yellow River Freight",
        "Zenith Cargo Partners", "Apex Perishables Broker", "Bright Pharma Express",
        "ColdChain Nexus", "DeepFreeze Logistics", "Eagle Cold Freight",
        "FrostLine Pharma Cargo", "Glacier Route Brokers", "Helix Bio Freight",
        "Ironwood Industrial Cargo", "JetCold Cold Chain", "Kestrel Pharma Lines",
        "Lumen Life Logistics", "MedBridge Cold Cargo", "Nimbus Fresh Freight",
        "Orchid Fresh Export", "Polar Star Perishables",
    ]

    for i in range(1, 51):
        cust_id = f"CUST-{i:03d}"
        seg = segments[(i - 1) % len(segments)]
        reg = regions[(i - 1) % len(regions)]
        tier = tiers[(i - 1) % len(tiers)]
        term = terms[(i - 1) % len(terms)]
        customers.append(
            {
                "customer_id": cust_id,
                "customer_name": names[i - 1],
                "industry_segment": seg,
                "region": reg,
                "tier": tier,
                "payment_terms": term,
            }
        )
    return customers


def generate_operational_data(customers):
    shipments = []
    legs = []

    chain_types = [
        ("SEA_AIR_TRUCK", 0.40),
        ("TRUCK_AIR_TRUCK", 0.35),
        ("DIRECT_AIR", 0.25),
    ]
    categories = [
        "General",
        "High_Tech",
        "E_Commerce",
        "Pharma_Cold_Chain",
        "Dangerous_Goods",
    ]
    sea_origins = ["CNYTN", "CNNGB", "CNSHA"]
    truck_origins = ["CNCAN", "SZX", "CNYTN"]
    destinations = ["LAX", "ORD", "LHR", "FRA", "NRT", "SIN", "SYD"]

    flight_dist = {
        "LAX": (11650, 780),
        "ORD": (12480, 840),
        "LHR": (9620, 720),
        "FRA": (9160, 690),
        "NRT": (2900, 240),
        "SIN": (2560, 210),
        "SYD": (7390, 550),
    }

    target_shipments = 7980
    leg_counter = 1

    for s_idx in range(1, target_shipments + 1):
        shipment_id = f"SHP-2025-{s_idx:06d}"
        customer = random.choice(customers)

        # Pick chain
        r = random.random()
        if r < 0.40:
            chain = "SEA_AIR_TRUCK"
            orig = random.choice(sea_origins)
        elif r < 0.75:
            chain = "TRUCK_AIR_TRUCK"
            orig = random.choice(truck_origins)
        else:
            chain = "DIRECT_AIR"
            orig = "HKG"

        dest = random.choice(destinations)
        cat = random.choice(categories)

        # Distribute booking_ts evenly across the 18 months
        day_offset = int((s_idx - 1) / target_shipments * TOTAL_DAYS)
        sec_offset = random.randint(0, 86399)
        booking_ts = START_DATE + timedelta(days=day_offset, seconds=sec_offset)

        weight_kg = round(random.uniform(150.0, 6500.0), 1)
        volume_cbm = round(weight_kg / random.uniform(140.0, 200.0), 2)
        pieces = max(1, int(weight_kg / random.uniform(15.0, 45.0)))

        shipment_legs = []
        current_time = booking_ts + timedelta(hours=random.uniform(4, 18))

        # Leg 1: Feeder
        if chain == "SEA_AIR_TRUCK":
            planned_dep = current_time
            planned_dur = random.uniform(28, 40)  # hours
            planned_arr = planned_dep + timedelta(hours=planned_dur)

            # Check Yantian congestion anomaly
            is_yantian_anomaly = (
                orig == "CNYTN"
                and YANTIAN_START <= planned_dep <= YANTIAN_END
            )

            if is_yantian_anomaly:
                delay_min = round(random.uniform(3200.0, 4200.0), 1)
            else:
                delay_min = (
                    round(random.uniform(-30.0, 120.0), 1)
                    if random.random() > 0.15
                    else round(random.uniform(180.0, 600.0), 1)
                )

            actual_dep = planned_dep + timedelta(
                minutes=random.uniform(0, 40)
            )
            actual_arr = planned_arr + timedelta(minutes=delay_min)
            dist_km = 45.0 if orig == "CNYTN" else 1250.0
            leg_cost = round(120.0 + weight_kg * 0.12, 2)

            leg_1 = {
                "leg_id": f"LEG-{leg_counter:06d}",
                "shipment_id": shipment_id,
                "leg_sequence": 1,
                "transport_mode": "SEA",
                "origin_facility": orig,
                "destination_facility": "HKG",
                "carrier_code": "Feeder_Line_A",
                "voyage_flight_no": f"FL-{random.randint(100, 999)}",
                "planned_depart_ts": planned_dep.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "actual_depart_ts": actual_dep.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "planned_arrive_ts": planned_arr.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "actual_arrive_ts": actual_arr.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "delay_minutes": delay_min,
                "distance_km": dist_km,
                "allocated_cost_usd": leg_cost,
                "leg_status": "COMPLETED" if delay_min <= 240 else "DELAYED",
            }
            leg_counter += 1
            shipment_legs.append(leg_1)
            current_time = actual_arr

        elif chain == "TRUCK_AIR_TRUCK":
            planned_dep = current_time
            planned_dur = random.uniform(3, 7)  # hours
            planned_arr = planned_dep + timedelta(hours=planned_dur)

            delay_min = (
                round(random.uniform(-15.0, 30.0), 1)
                if random.random() > 0.12
                else round(random.uniform(45.0, 180.0), 1)
            )
            # Shenzhen Bay congestion: SZX feeder trucks queue 2-6 h extra
            if orig == "SZX" and TRUCK_START <= planned_dep <= TRUCK_END:
                delay_min = round(random.uniform(120.0, 360.0), 1)
            actual_dep = planned_dep + timedelta(
                minutes=random.uniform(0, 20)
            )
            actual_arr = planned_arr + timedelta(minutes=delay_min)
            dist_km = random.uniform(80.0, 190.0)
            leg_cost = round(80.0 + weight_kg * 0.18, 2)

            leg_1 = {
                "leg_id": f"LEG-{leg_counter:06d}",
                "shipment_id": shipment_id,
                "leg_sequence": 1,
                "transport_mode": "TRUCK",
                "origin_facility": orig,
                "destination_facility": "HKG",
                "carrier_code": "CrossBorder_Fleet_B",
                "voyage_flight_no": f"TRK-{random.randint(100, 999)}",
                "planned_depart_ts": planned_dep.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "actual_depart_ts": actual_dep.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "planned_arrive_ts": planned_arr.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "actual_arrive_ts": actual_arr.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "delay_minutes": delay_min,
                "distance_km": round(dist_km, 1),
                "allocated_cost_usd": leg_cost,
                "leg_status": "COMPLETED" if delay_min <= 60 else "DELAYED",
            }
            leg_counter += 1
            shipment_legs.append(leg_1)
            current_time = actual_arr

        # Leg 2 (or 1): AIR Leg departing HKG
        air_seq = 2 if chain != "DIRECT_AIR" else 1

        # Planned air departure: at least 6-12h dwell time after planned arrival of leg 1
        dwell_planned_hours = random.uniform(6, 12)
        if chain == "DIRECT_AIR":
            air_planned_dep = current_time + timedelta(
                hours=random.uniform(2, 6)
            )
        else:
            first_planned_arr = datetime.strptime(
                shipment_legs[0]["planned_arrive_ts"], "%Y-%m-%dT%H:%M:%SZ"
            )
            air_planned_dep = first_planned_arr + timedelta(
                hours=dwell_planned_hours
            )

        dist_km, flight_min = flight_dist[dest]
        air_planned_arr = air_planned_dep + timedelta(minutes=flight_min)

        # Typhoon anomaly condition
        is_typhoon_window = (
            TYPHOON_START <= air_planned_dep <= TYPHOON_END
        )

        # Check if missed connection due to feeder delay
        missed_connection = (
            chain != "DIRECT_AIR"
            and current_time > air_planned_dep - timedelta(hours=2)
        )

        if is_typhoon_window:
            # Over 65% severe delays/cancellations, OTP < 40%
            if random.random() < 0.68:
                air_delay_min = round(random.uniform(90.0, 2400.0), 1)
            else:
                air_delay_min = round(random.uniform(-10.0, 14.0), 1)
        elif missed_connection:
            # Re-accommodate cargo on a later flight. The delay must exceed the
            # feeder lateness so the air leg never departs before the cargo
            # physically arrives at HKG (dwell stays >= ~1.5 h).
            lateness_min = (current_time - air_planned_dep).total_seconds() / 60.0
            rebook_min = lateness_min + random.uniform(90.0, 240.0)
            air_delay_min = round(max(rebook_min, random.uniform(1380.0, 1560.0)), 1)
        else:
            # Normal operations: ~89% OTP
            if random.random() < 0.89:
                air_delay_min = round(random.uniform(-12.0, 14.0), 1)
            else:
                air_delay_min = round(random.uniform(35.0, 240.0), 1)

        air_actual_dep = air_planned_dep + timedelta(minutes=air_delay_min)
        air_actual_arr = air_planned_arr + timedelta(minutes=air_delay_min)

        # Air cost modeling
        # June 2026 HKG-ORD pricing anomaly
        is_ord_anomaly = (
            dest == "ORD"
            and ORD_ANOMALY_START <= air_planned_dep <= ORD_ANOMALY_END
        )

        if is_ord_anomaly:
            # Cost exceeds revenue: charter/fuel cost $3.50/kg
            air_cost = round(weight_kg * random.uniform(3.40, 3.70), 2)
        else:
            air_cost = round(
                weight_kg * (dist_km / 10000.0) * random.uniform(1.80, 2.30),
                2,
            )

        air_leg = {
            "leg_id": f"LEG-{leg_counter:06d}",
            "shipment_id": shipment_id,
            "leg_sequence": air_seq,
            "transport_mode": "AIR",
            "origin_facility": "HKG",
            "destination_facility": dest,
            "carrier_code": "CX",
            "voyage_flight_no": f"CX{random.randint(800, 899)}",
            "planned_depart_ts": air_planned_dep.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "actual_depart_ts": air_actual_dep.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "planned_arrive_ts": air_planned_arr.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "actual_arrive_ts": air_actual_arr.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "delay_minutes": air_delay_min,
            "distance_km": float(dist_km),
            "allocated_cost_usd": air_cost,
            "leg_status": "COMPLETED" if abs(air_delay_min) <= 15 else "DELAYED",
        }
        leg_counter += 1
        shipment_legs.append(air_leg)
        current_time = air_actual_arr

        # Leg 3 (or 2): Final delivery truck leg
        last_seq = air_seq + 1
        truck_planned_dep = air_planned_arr + timedelta(
            hours=random.uniform(2, 5)
        )
        truck_planned_arr = truck_planned_dep + timedelta(
            hours=random.uniform(2, 6)
        )

        delivery_delay = (
            round(random.uniform(-10.0, 25.0), 1)
            if random.random() > 0.10
            else round(random.uniform(40.0, 150.0), 1)
        )
        truck_actual_dep = max(current_time, truck_planned_dep)
        truck_actual_arr = truck_planned_arr + timedelta(
            minutes=air_delay_min + delivery_delay
        )
        truck_cost = round(120.0 + weight_kg * 0.15, 2)

        delivery_leg = {
            "leg_id": f"LEG-{leg_counter:06d}",
            "shipment_id": shipment_id,
            "leg_sequence": last_seq,
            "transport_mode": "TRUCK",
            "origin_facility": dest,
            "destination_facility": f"{dest}_METRO",
            "carrier_code": "Dest_Logistics_X",
            "voyage_flight_no": f"DLV-{random.randint(100, 999)}",
            "planned_depart_ts": truck_planned_dep.strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "actual_depart_ts": truck_actual_dep.strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "planned_arrive_ts": truck_planned_arr.strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "actual_arrive_ts": truck_actual_arr.strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "delay_minutes": round(
                (truck_actual_arr - truck_planned_arr).total_seconds() / 60.0,
                1,
            ),
            "distance_km": round(random.uniform(45.0, 160.0), 1),
            "allocated_cost_usd": truck_cost,
            "leg_status": "COMPLETED"
            if (truck_actual_arr - truck_planned_arr).total_seconds() <= 3600
            else "DELAYED",
        }
        leg_counter += 1
        shipment_legs.append(delivery_leg)

        # Aggregate shipment financials
        total_actual_cost = round(
            sum(l["allocated_cost_usd"] for l in shipment_legs), 2
        )
        est_cost = round(total_actual_cost * random.uniform(0.92, 1.05), 2)

        if is_ord_anomaly:
            # Underbilled contracted revenue: $1.85/kg floor -> negative margin (-18% to -23%)
            contracted_rev = round(
                total_actual_cost * random.uniform(0.78, 0.84), 2
            )
        else:
            # Normal gross margin 15% - 30%
            contracted_rev = round(
                total_actual_cost * random.uniform(1.18, 1.32), 2
            )

        final_planned_arr = shipment_legs[-1]["planned_arrive_ts"]
        final_actual_arr = shipment_legs[-1]["actual_arrive_ts"]
        final_delay_min = (
            datetime.strptime(final_actual_arr, "%Y-%m-%dT%H:%M:%SZ")
            - datetime.strptime(final_planned_arr, "%Y-%m-%dT%H:%M:%SZ")
        ).total_seconds() / 60.0

        if final_delay_min <= 60:  # end-to-end tolerance: within 1 hour
            status = "DELIVERED"
        elif final_delay_min > 1440:
            status = "EXCEPTION"
        else:
            status = "DELAYED"

        shipments.append(
            {
                "shipment_id": shipment_id,
                "customer_id": customer["customer_id"],
                "origin_location": orig,
                "destination_location": dest,
                "transport_chain_type": chain,
                "cargo_category": cat,
                "total_chargeable_weight_kg": weight_kg,
                "total_volume_cbm": volume_cbm,
                "total_pieces": pieces,
                "booking_ts": booking_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "contracted_revenue_usd": contracted_rev,
                "estimated_cost_usd": est_cost,
                "actual_cost_usd": total_actual_cost,
                "status": status,
            }
        )

        legs.extend(shipment_legs)

    return shipments, legs


def generate_air_kpis():
    lanes = [
        ("HKG-LAX", 11650),
        ("HKG-ORD", 12480),
        ("HKG-LHR", 9620),
        ("HKG-FRA", 9160),
        ("HKG-NRT", 2900),
        ("HKG-SIN", 2560),
        ("HKG-SYD", 7390),
        ("HKG-TPE", 800),
        ("HKG-ICN", 2100),
        ("HKG-DXB", 5900),
    ]

    records = []
    current_date = START_DATE.date()
    end_date = END_DATE.date()

    while current_date <= end_date:
        is_typhoon = (
            TYPHOON_START.date() <= current_date <= TYPHOON_END.date()
        )

        for lane, dist in lanes:
            sched = random.randint(2, 5)

            if is_typhoon:
                canc = int(sched * random.uniform(0.4, 0.7))
                comp = sched - canc
                otp_arr = round(random.uniform(0.28, 0.44), 3)
                otp_dep = round(random.uniform(0.25, 0.40), 3)
                clf = round(random.uniform(0.55, 0.70), 3)
                backlog = round(random.uniform(2800.0, 4200.0), 1)
            else:
                canc = 0 if random.random() > 0.05 else 1
                comp = max(0, sched - canc)
                otp_arr = round(random.uniform(0.85, 0.94), 3)
                otp_dep = round(random.uniform(0.86, 0.95), 3)
                clf = round(random.uniform(0.76, 0.88), 3)
                backlog = round(random.uniform(500.0, 1200.0), 1)

            atk = round(comp * (dist * 105.0) / 1000.0, 1)  # tonnes * dist / 1k
            rtk = round(atk * clf, 1)
            yield_usd = round(random.uniform(0.28, 0.42), 4)
            # HKG-ORD pricing error: contracted yield collapses below cost in June 2026
            if (
                lane == "HKG-ORD"
                and ORD_ANOMALY_START.date() <= current_date <= ORD_ANOMALY_END.date()
            ):
                yield_usd = round(random.uniform(0.16, 0.20), 4)

            records.append(
                {
                    "report_date": current_date.strftime("%Y-%m-%d"),
                    "route_lane": lane,
                    "scheduled_flights": sched,
                    "completed_flights": comp,
                    "cancelled_flights": canc,
                    "atk_thousand": atk,
                    "rtk_thousand": rtk,
                    "cargo_load_factor": clf,
                    "on_time_departure_rate": otp_dep,
                    "on_time_arrival_rate": otp_arr,
                    "cargo_yield_per_rtk_usd": yield_usd,
                    "backlog_tonnes": backlog,
                }
            )

        current_date += timedelta(days=1)

    return records


def generate_ocean_rates():
    corridors = [
        "PRD_FEEDER_HKG",
        "YANTIAN_FEEDER_HKG",
        "NINGBO_COASTAL_HKG",
        "SHANGHAI_COASTAL_HKG",
    ]
    records = []
    current_date = START_DATE.date()

    # Advance to first Friday
    while current_date.weekday() != 4:
        current_date += timedelta(days=1)

    while current_date <= END_DATE.date():
        for cor in corridors:
            base_rate = (
                random.uniform(420, 680)
                if "FEEDER" in cor
                else random.uniform(750, 1100)
            )
            # Yantian congestion: feeder spot rates spike during the event window
            if cor == "YANTIAN_FEEDER_HKG" and YANTIAN_START.date() <= current_date <= YANTIAN_END.date():
                base_rate *= random.uniform(1.35, 1.55)
            baf = round(base_rate * random.uniform(0.12, 0.18), 1)
            thc = round(random.uniform(140, 220), 1)
            records.append(
                {
                    "week_start_date": current_date.strftime("%Y-%m-%d"),
                    "feeder_corridor": cor,
                    "average_rate_per_feu_usd": round(base_rate, 1),
                    "fuel_surcharge_baf": baf,
                    "terminal_handling_charge_usd": thc,
                }
            )
        current_date += timedelta(days=7)

    return records


def generate_sea_kpis():
    """Weekly feeder performance per corridor — sea's first-class KPI series."""
    corridors = [
        "PRD_FEEDER_HKG",
        "YANTIAN_FEEDER_HKG",
        "NINGBO_COASTAL_HKG",
        "SHANGHAI_COASTAL_HKG",
    ]
    records = []
    current_date = START_DATE.date()
    while current_date.weekday() != 0:  # weeks start Monday
        current_date += timedelta(days=1)

    while current_date <= END_DATE.date():
        in_yantian = YANTIAN_START.date() <= current_date <= YANTIAN_END.date()
        for cor in corridors:
            sched = random.randint(4, 9)
            canc = int(sched * random.uniform(0.15, 0.35)) if (in_yantian and cor == "YANTIAN_FEEDER_HKG") else (1 if random.random() < 0.04 else 0)
            comp = max(0, sched - canc)
            if in_yantian and cor == "YANTIAN_FEEDER_HKG":
                otp = round(random.uniform(0.42, 0.60), 3)
                transit = round(random.uniform(52.0, 68.0), 1)  # baseline ~30
                backlog = round(random.uniform(180.0, 320.0), 1)
            else:
                otp = round(random.uniform(0.84, 0.94), 3)
                transit = round(random.uniform(26.0, 36.0), 1)
                backlog = round(random.uniform(20.0, 80.0), 1)
            records.append(
                {
                    "week_start_date": current_date.strftime("%Y-%m-%d"),
                    "feeder_corridor": cor,
                    "scheduled_sailings": sched,
                    "completed_sailings": comp,
                    "cancelled_sailings": canc,
                    "on_time_departure_rate": otp,
                    "avg_transit_hours": transit,
                    "slot_utilization": round(random.uniform(0.72, 0.95), 3),
                    "backlog_teu": backlog,
                }
            )
        current_date += timedelta(days=7)
    return records


def generate_truck_kpis():
    """Daily cross-border truck performance per GBA checkpoint."""
    records = []
    current_date = START_DATE.date()
    end_date = END_DATE.date()

    while current_date <= end_date:
        in_congestion = TRUCK_START.date() <= current_date <= TRUCK_END.date()
        for cp in TRUCK_CHECKPOINTS:
            sched = random.randint(14, 26)
            if in_congestion and cp == "SZBP":
                canc = int(sched * random.uniform(0.10, 0.22))
                comp = sched - canc
                otp = round(random.uniform(0.48, 0.66), 3)
                crossing = round(random.uniform(150.0, 260.0), 1)  # baseline ~45
                backlog = round(random.uniform(120.0, 220.0), 1)
            else:
                canc = 1 if random.random() < 0.03 else 0
                comp = sched - canc
                otp = round(random.uniform(0.84, 0.94), 3)
                crossing = round(random.uniform(35.0, 55.0), 1)
                backlog = round(random.uniform(5.0, 25.0), 1)
            records.append(
                {
                    "report_date": current_date.strftime("%Y-%m-%d"),
                    "checkpoint": cp,
                    "scheduled_trips": sched,
                    "completed_trips": comp,
                    "cancelled_trips": canc,
                    "on_time_arrival_rate": otp,
                    "avg_crossing_minutes": crossing,
                    "queue_backlog_trucks": backlog,
                    "avg_cost_per_tonne_usd": round(random.uniform(38.0, 55.0), 2),
                }
            )
        current_date += timedelta(days=1)
    return records


def generate_rate_cards():
    records = []
    zones = [
        ("HKG", "LAX", "AIR"),
        ("HKG", "ORD", "AIR"),
        ("HKG", "LHR", "AIR"),
        ("HKG", "FRA", "AIR"),
        ("HKG", "NRT", "AIR"),
        ("CNYTN", "HKG", "SEA"),
        ("CNSHA", "HKG", "SEA"),
        ("CNCAN", "HKG", "TRUCK"),
        ("SZX", "HKG", "TRUCK"),
    ]

    breaks = [
        ("MIN", 80.0),
        ("+0KG", 4.2),
        ("+300KG", 3.6),
        ("+1000KG", 2.9),
        ("PER_FEU", 550.0),
        ("PER_TRUCK", 320.0),
    ]

    card_id = 1
    for orig, dest, mode in zones:
        for wb, rate in breaks:
            if mode == "AIR" and "PER_" in wb:
                continue
            if mode != "AIR" and "+1000" in wb:
                continue
            if mode != "TRUCK" and wb == "PER_TRUCK":
                continue

            records.append(
                {
                    "rate_id": f"RC-{card_id:04d}",
                    "transport_mode": mode,
                    "origin_zone": orig,
                    "dest_zone": dest,
                    "weight_break": wb,
                    "base_rate_usd": rate,
                    "effective_start_date": "2025-01-01",
                    "effective_end_date": "2026-12-31",
                }
            )
            card_id += 1

    return records


def generate_disruption_events():
    return [
        {
            "event_id": "EVT-2025-001",
            "event_code": "TYPHOON_2025_09",
            "event_category": "WEATHER",
            "affected_mode": "AIR",
            "start_timestamp": "2025-09-15T00:00:00Z",
            "end_timestamp": "2025-09-21T23:59:59Z",
            "primary_location": "HKG",
            "description": "Super Typhoon simulated strike directly impacting HKG apron and cargo terminal operations with extensive flight cancellations.",
            "target_metric_impact": "air_otp_drop_below_50_backlog_spike",
        },
        {
            "event_id": "EVT-2025-002",
            "event_code": "SHENZHEN_BAY_CONGESTION_2025_11",
            "event_category": "BORDER_CONGESTION",
            "affected_mode": "TRUCK",
            "start_timestamp": "2025-11-10T00:00:00Z",
            "end_timestamp": "2025-11-24T23:59:59Z",
            "primary_location": "SZBP",
            "description": "Enhanced inspection and holiday surge at Shenzhen Bay checkpoint stall cross-border feeder trucks; queue backlog triples and SZX feeder legs miss planned HKG connections.",
            "target_metric_impact": "truck_otp_below_70_crossing_time_triple",
        },
        {
            "event_id": "EVT-2026-002",
            "event_code": "YANTIAN_CONGESTION_2026_03",
            "event_category": "PORT_CONGESTION",
            "affected_mode": "SEA",
            "start_timestamp": "2026-03-01T00:00:00Z",
            "end_timestamp": "2026-03-15T23:59:59Z",
            "primary_location": "CNYTN",
            "description": "Severe berth and yard crane congestion at Shenzhen Yantian Feeder Terminal delaying barges to HKG Marine Terminal.",
            "target_metric_impact": "feeder_sea_delay_over_3000_min_missed_connections",
        },
        {
            "event_id": "EVT-2026-003",
            "event_code": "PRICING_ERROR_2026_06",
            "event_category": "COMMERCIAL_MISCONFIGURATION",
            "affected_mode": "COMMERCIAL",
            "start_timestamp": "2026-06-01T00:00:00Z",
            "end_timestamp": "2026-06-30T23:59:59Z",
            "primary_location": "HKG",
            "description": "Contract rate misconfiguration on HKG-ORD Transpacific corridor underbilling contracted revenue below actual charter and fuel cost.",
            "target_metric_impact": "negative_gross_margin_transpacific",
        },
    ]


def save_csv(filename, fieldnames, rows):
    path = SYNTHETIC_DIR / filename
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[OK] Wrote {len(rows)} records to {filename}")


def main():
    print(
        f"[INFO] Generating synthetic operational data (Seed: {RANDOM_SEED})..."
    )

    customers = generate_customers()
    save_csv(
        "dim_customers.csv",
        [
            "customer_id",
            "customer_name",
            "industry_segment",
            "region",
            "tier",
            "payment_terms",
        ],
        customers,
    )

    shipments, legs = generate_operational_data(customers)
    save_csv(
        "dim_shipments.csv",
        [
            "shipment_id",
            "customer_id",
            "origin_location",
            "destination_location",
            "transport_chain_type",
            "cargo_category",
            "total_chargeable_weight_kg",
            "total_volume_cbm",
            "total_pieces",
            "booking_ts",
            "contracted_revenue_usd",
            "estimated_cost_usd",
            "actual_cost_usd",
            "status",
        ],
        shipments,
    )

    save_csv(
        "fact_shipment_legs.csv",
        [
            "leg_id",
            "shipment_id",
            "leg_sequence",
            "transport_mode",
            "origin_facility",
            "destination_facility",
            "carrier_code",
            "voyage_flight_no",
            "planned_depart_ts",
            "actual_depart_ts",
            "planned_arrive_ts",
            "actual_arrive_ts",
            "delay_minutes",
            "distance_km",
            "allocated_cost_usd",
            "leg_status",
        ],
        legs,
    )

    air_kpis = generate_air_kpis()
    save_csv(
        "fact_air_kpi_daily.csv",
        [
            "report_date",
            "route_lane",
            "scheduled_flights",
            "completed_flights",
            "cancelled_flights",
            "atk_thousand",
            "rtk_thousand",
            "cargo_load_factor",
            "on_time_departure_rate",
            "on_time_arrival_rate",
            "cargo_yield_per_rtk_usd",
            "backlog_tonnes",
        ],
        air_kpis,
    )

    ocean_rates = generate_ocean_rates()
    save_csv(
        "fact_ocean_rate_weekly.csv",
        [
            "week_start_date",
            "feeder_corridor",
            "average_rate_per_feu_usd",
            "fuel_surcharge_baf",
            "terminal_handling_charge_usd",
        ],
        ocean_rates,
    )

    sea_kpis = generate_sea_kpis()
    save_csv(
        "fact_sea_kpi_weekly.csv",
        [
            "week_start_date",
            "feeder_corridor",
            "scheduled_sailings",
            "completed_sailings",
            "cancelled_sailings",
            "on_time_departure_rate",
            "avg_transit_hours",
            "slot_utilization",
            "backlog_teu",
        ],
        sea_kpis,
    )

    truck_kpis = generate_truck_kpis()
    save_csv(
        "fact_truck_kpi_daily.csv",
        [
            "report_date",
            "checkpoint",
            "scheduled_trips",
            "completed_trips",
            "cancelled_trips",
            "on_time_arrival_rate",
            "avg_crossing_minutes",
            "queue_backlog_trucks",
            "avg_cost_per_tonne_usd",
        ],
        truck_kpis,
    )

    rate_cards = generate_rate_cards()
    save_csv(
        "fact_rate_cards.csv",
        [
            "rate_id",
            "transport_mode",
            "origin_zone",
            "dest_zone",
            "weight_break",
            "base_rate_usd",
            "effective_start_date",
            "effective_end_date",
        ],
        rate_cards,
    )

    events = generate_disruption_events()
    save_csv(
        "fact_disruption_events.csv",
        [
            "event_id",
            "event_code",
            "event_category",
            "affected_mode",
            "start_timestamp",
            "end_timestamp",
            "primary_location",
            "description",
            "target_metric_impact",
        ],
        events,
    )

    print("[OK] Synthetic operational data generation complete.")


if __name__ == "__main__":
    main()
