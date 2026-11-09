# Milestone & Message-Code Mapping (R4-1)

> Source of truth: `backend/app/ingest/standards.py`. This table is generated from
> `MILESTONE_STANDARDS`. Only the **public** parts of each standard are used
> (status-code lists, event categories). We do **not** claim conformance to DCSA
> v3 — its full spec needs member access (see `NETWORK_UPGRADE_PLAN.md` R10 / §2.4).

The project keeps 6 internal Cargo-iQ-style milestone codes and maps them onto
the vocabularies the industry exchanges. The FSU ingest parser accepts any alias
in the "CIMP aliases" column and resolves it to the internal code; the event log
records events under the ONE Record-style name.

| Internal | Name | Cargo iQ (MOP) | ONE Record event | CIMP / Cargo-IMP aliases accepted | Scope |
|---|---|---|---|---|---|
| BKD | Booked | Booking | BookingConfirmed | BKD, BKG | SHIPMENT |
| RCS | Ready for Carriage | Received from Shipper | ReadyForCarriage | RCS, **FOH** (Freight On Hand) | SHIPMENT |
| DEP | Departed | Departed | Departed | DEP, **MAN** (Manifested), **LOD** (Loaded) | LEG |
| ARR | Arrived | Arrived | Arrived | ARR, **RCF** (Received from Flight) | LEG |
| NFD | Notified for Delivery | Notified | NotifiedForDelivery | NFD, **AWD** (Arrival docs delivered) | SHIPMENT |
| DLV | Delivered | Delivered | Delivered | DLV | SHIPMENT |

## How it is used

- **Ingest** (`app/ingest/fsu.py`): a line `FSU|RCF|SHP-...|FRA|<ts>` is accepted
  because `RCF` is a known alias, then stored as the internal `ARR` event. Unknown
  codes still land in `ingest_rejects` with a reason.
- **Event log** (`app/events/adapters.py`): `CODE_TO_EVENT_TYPE` emits the ONE
  Record-style name (`Arrived`) into `fact_event_log.event_type`.
- **Coverage** is measured against planned milestones in `v_data_quality`
  (R4-4), so a mapping gap would show up as reduced coverage, not a silent drop.

## Deliberate non-claims

- No DCSA v3 conformance claim (public page only exposes the five event
  categories; full spec is member-gated).
- CIMP alias list is illustrative of the common Cargo-IMP FSU status set, not an
  exhaustive CIMP implementation.
