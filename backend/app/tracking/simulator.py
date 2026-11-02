"""Deterministic position interpolation for the map view.

No live AIS/ADS-B feed exists for the synthetic dataset, so positions are
interpolated along the great-circle (air/sea) or straight (truck) path between
leg endpoints, parameterised by the planned schedule. The contract matches what
a real feed would return — swap the simulator for a provider without touching
the frontend.
"""

import math
from typing import Any

from app.config import get_settings

# Real-world coordinates for the network's facilities
LOCATIONS: dict[str, dict[str, Any]] = {
    "CNSHA": {"name": "Shanghai", "kind": "seaport", "lat": 31.2304, "lon": 121.4737},
    "CNNGB": {"name": "Ningbo", "kind": "seaport", "lat": 29.8683, "lon": 121.5440},
    "CNYTN": {"name": "Yantian", "kind": "seaport", "lat": 22.5759, "lon": 114.2648},
    "CNCAN": {"name": "Guangzhou", "kind": "seaport", "lat": 23.1291, "lon": 113.2644},
    "SZX": {"name": "Shenzhen", "kind": "checkpoint", "lat": 22.5431, "lon": 114.0579},
    "HKG": {"name": "Hong Kong", "kind": "airport", "lat": 22.3080, "lon": 113.9185},
    "LAX": {"name": "Los Angeles", "kind": "airport", "lat": 33.9416, "lon": -118.4085},
    "ORD": {"name": "Chicago", "kind": "airport", "lat": 41.9742, "lon": -87.9073},
    "LHR": {"name": "London", "kind": "airport", "lat": 51.4700, "lon": -0.4543},
    "FRA": {"name": "Frankfurt", "kind": "airport", "lat": 50.0379, "lon": 8.5622},
    "NRT": {"name": "Tokyo", "kind": "airport", "lat": 35.7720, "lon": 140.3929},
    "SIN": {"name": "Singapore", "kind": "airport", "lat": 1.3644, "lon": 103.9915},
    "SYD": {"name": "Sydney", "kind": "airport", "lat": -33.9399, "lon": 151.1753},
}

MODE_COLOR = {"SEA": "#818cf8", "AIR": "#22d3ee", "TRUCK": "#34d399"}


def _great_circle_points(lat1, lon1, lat2, lon2, n):
    """Slerp between two points on the sphere — n intermediate points."""
    if abs(lat1 - lat2) < 1e-9 and abs(lon1 - lon2) < 1e-9:
        return [(lat1, lon1)]
    rad = math.pi / 180.0
    p1 = (90 - lat1) * rad
    p2 = (90 - lat2) * rad
    t1 = lon1 * rad
    t2 = lon2 * rad
    cosd = math.sin(p1) * math.sin(p2) * math.cos(t1 - t2) + math.cos(p1) * math.cos(p2)
    cosd = max(-1.0, min(1.0, cosd))
    d = math.acos(cosd)
    if d == 0:
        return [(lat1, lon1)]
    pts = []
    for f in (i / n for i in range(n + 1)):
        a = math.sin((1 - f) * d) / math.sin(d)
        b = math.sin(f * d) / math.sin(d)
        x = a * math.sin(p1) * math.cos(t1) + b * math.sin(p2) * math.cos(t2)
        y = a * math.sin(p1) * math.sin(t1) + b * math.sin(p2) * math.sin(t2)
        z = a * math.cos(p1) + b * math.cos(p2)
        lat = (math.atan2(z, math.hypot(x, y))) / rad
        lon = (math.atan2(y, x)) / rad
        pts.append((round(lat, 4), round(lon, 4)))
    return pts


def leg_track(leg: dict[str, Any], points_per_leg: int = 24) -> dict[str, Any] | None:
    """Interpolate one leg into a polyline. Returns None for unknown facilities."""
    o = LOCATIONS.get(leg["origin_facility"])
    d = LOCATIONS.get(leg["destination_facility"].removesuffix("_METRO"))
    if not o or not d:
        return None
    mode = leg["transport_mode"]
    n = max(2, points_per_leg if mode != "TRUCK" else 6)
    coords = _great_circle_points(o["lat"], o["lon"], d["lat"], d["lon"], n)
    return {
        "leg_id": leg["leg_id"],
        "mode": mode,
        "color": MODE_COLOR.get(mode, "#94a3b8"),
        "origin": leg["origin_facility"],
        "destination": leg["destination_facility"],
        "coords": [{"lat": la, "lon": lo} for la, lo in coords],
    }


def shipment_tracks(legs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tracks = []
    for leg in sorted(legs, key=lambda l: l["leg_sequence"]):
        t = leg_track(leg)
        if t:
            tracks.append(t)
    return tracks


def seed_locations() -> list[dict[str, Any]]:
    return [
        {"code": code, "name": v["name"], "kind": v["kind"], "lat": v["lat"], "lon": v["lon"]}
        for code, v in LOCATIONS.items()
    ]
