"""Multi-source event layer (P1).

Normalizes events from several sources (ops clock, FSU ingest, capacity changes)
into an append-only `fact_event_log`, then projects them to read models
(milestone events, capacity state). ONE Record-style event-type naming.
"""
