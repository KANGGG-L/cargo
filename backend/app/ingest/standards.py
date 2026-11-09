"""Standard milestone/message code mapping (R4-1).

Maps the project's 6 internal Cargo-iQ-style milestone codes onto the public
vocabularies the industry actually exchanges:

- IATA CIMP / Cargo-IMP FSU status codes (FOH, RCS, MAN, DEP, ARR, RCF, NFD, DLV ...)
- IATA Cargo iQ MOP milestones
- ONE Record-style LogisticsEvent type names (R4-1, see app/events/adapters.py)

Only the PUBLIC parts of the standards are used (status-code lists, event
categories). We deliberately do NOT claim conformance to DCSA v3 (its full spec
needs member access — see docs/NETWORK_UPGRADE_PLAN.md R10 / §2.4). The map is
the single source of truth for alias resolution in the FSU parser and for the
docs/MILESTONE_MAPPING.md table.
"""

# internal code -> standard descriptors
MILESTONE_STANDARDS: dict[str, dict] = {
    "BKD": {
        "name": "Booked",
        "cargo_iq": "Booking",
        "one_record": "BookingConfirmed",
        "cimp_aliases": ["BKD", "BKG"],
        "mode": "SHIPMENT",
    },
    "RCS": {
        "name": "Ready for Carriage",
        "cargo_iq": "Received from Shipper",
        "one_record": "ReadyForCarriage",
        "cimp_aliases": ["RCS", "FOH"],  # FOH = Freight On Hand
        "mode": "SHIPMENT",
    },
    "DEP": {
        "name": "Departed",
        "cargo_iq": "Departed",
        "one_record": "Departed",
        "cimp_aliases": ["DEP", "MAN", "LOD"],  # MAN=Manifested, LOD=Loaded
        "mode": "LEG",
    },
    "ARR": {
        "name": "Arrived",
        "cargo_iq": "Arrived",
        "one_record": "Arrived",
        "cimp_aliases": ["ARR", "RCF"],  # RCF = Received from Flight
        "mode": "LEG",
    },
    "NFD": {
        "name": "Notified for Delivery",
        "cargo_iq": "Notified",
        "one_record": "NotifiedForDelivery",
        "cimp_aliases": ["NFD", "AWD"],  # AWD = Arrival documents delivered
        "mode": "SHIPMENT",
    },
    "DLV": {
        "name": "Delivered",
        "cargo_iq": "Delivered",
        "one_record": "Delivered",
        "cimp_aliases": ["DLV", "DLV"],
        "mode": "SHIPMENT",
    },
}

# reverse: any accepted CIMP/standard code -> internal code
ALIAS_TO_INTERNAL: dict[str, str] = {}
for _internal, _meta in MILESTONE_STANDARDS.items():
    ALIAS_TO_INTERNAL[_internal] = _internal
    for _alias in _meta["cimp_aliases"]:
        ALIAS_TO_INTERNAL[_alias] = _internal


def resolve_code(raw_code: str) -> str | None:
    """Resolve a reported code (internal or CIMP alias) to an internal code."""
    return ALIAS_TO_INTERNAL.get(raw_code.upper())


# the full set of codes the FSU parser accepts (internal + all aliases)
ACCEPTED_CODES = set(ALIAS_TO_INTERNAL)
