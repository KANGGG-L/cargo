export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export interface OverviewKpis {
  air_otp_pct: number;
  sea_otp_pct: number;
  truck_otp_pct: number;
  multimodal_otp_pct: number;
  load_factor_pct: number;
  avg_dwell_hours: number;
  total_shipments: number;
  total_tonnes: number;
  total_revenue_musd: number;
  total_cost_musd: number;
  gross_margin_pct: number;
}

export interface DisruptionEvent {
  event_id: string;
  event_code: string;
  event_category: string;
  affected_mode: string;
  start_timestamp: string;
  end_timestamp: string;
  primary_location: string;
  description: string;
}

export interface OverviewPayload {
  kpis: OverviewKpis;
  recent_disruptions: DisruptionEvent[];
}

export interface TrendPoint {
  date: string;
  air_otp_pct: number;
  load_factor_pct: number;
  backlog_tonnes: number;
}

export interface MonthlyPoint {
  month: string;
  shipments: number;
  revenue_musd: number;
  cost_musd: number;
  gross_margin_pct: number;
}

export interface WeeklyRatePoint {
  week: string;
  yantian_feu: number | null;
  prd_feu: number | null;
}

export interface TruckDailyPoint {
  date: string;
  truck_otp_pct: number;
  avg_crossing_minutes: number;
  avg_backlog_trucks: number;
}

export interface SeaWeeklyPoint {
  week: string;
  corridor: string;
  sea_otp_pct: number;
  avg_transit_hours: number;
  cancelled_sailings: number;
  backlog_teu: number;
}

export interface TrendsPayload {
  daily: TrendPoint[];
  monthly: MonthlyPoint[];
  daily_truck: TruckDailyPoint[];
  weekly_sea: SeaWeeklyPoint[];
  weekly_rates: WeeklyRatePoint[];
}

export interface AirLane {
  dest: string;
  legs: number;
  tonnes: number;
  revenue_musd: number;
  avg_delay_min: number;
}

export interface FeederPort {
  port: string;
  legs: number;
  avg_delay_hours: number;
  sea_otp_pct: number;
}

export interface ModeSplit {
  mode: string;
  legs: number;
  thousand_km: number;
}

export interface ChainMix {
  chain: string;
  shipments: number;
  revenue_musd: number;
}

export interface TruckCheckpoint {
  checkpoint: string;
  truck_otp_pct: number;
  avg_crossing_minutes: number;
  avg_backlog_trucks: number;
  cancelled_trips: number;
}

export interface NetworkPayload {
  mode_split: ModeSplit[];
  chain_mix: ChainMix[];
  air_lanes: AirLane[];
  feeder_ports: FeederPort[];
  truck_checkpoints: TruckCheckpoint[];
}

/** Demo session: ops account auto-login (cookie kept for :8000). One-shot. */
let sessionPromise: Promise<void> | null = null;
export function ensureSession(): Promise<void> {
  if (!sessionPromise) {
    sessionPromise = fetch(`${API_BASE}/api/portal/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ email: "ops@demo.local", password: "demo1234" }),
    })
      .then(() => undefined)
      .catch(() => undefined);
  }
  return sessionPromise;
}

async function getJson<T>(path: string): Promise<T> {
  await ensureSession();
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store", credentials: "include" });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json() as Promise<T>;
}

export interface ShipmentListItem {
  shipment_id: string;
  transport_chain_type: string;
  cargo_category: string;
  status: string;
  origin_location: string;
  destination_location: string;
  total_chargeable_weight_kg: number;
  contracted_revenue_usd: number;
  booking_ts: string;
  customer_name: string;
}

export interface TraceLeg {
  leg_id: string;
  leg_sequence: number;
  transport_mode: string;
  origin_facility: string;
  destination_facility: string;
  carrier_code: string;
  voyage_flight_no: string;
  planned_depart_ts: string;
  actual_depart_ts: string;
  planned_arrive_ts: string;
  actual_arrive_ts: string;
  delay_minutes: number;
  distance_km: number;
  allocated_cost_usd: number;
  leg_status: string;
}

export interface TracePayload {
  shipment: ShipmentListItem & {
    estimated_cost_usd: number;
    actual_cost_usd: number;
    region: string;
  };
  legs: TraceLeg[];
}

export interface SankeyPayload {
  nodes: { name: string }[];
  links: { source: string; target: string; value: number }[];
}

export interface AlertItem {
  alert_id: string;
  shipment_id: string;
  rule_id: string | null;
  source: string;
  severity: string;
  title: string;
  detail: string;
  status: string;
  created_ts: string;
  updated_ts: string;
  assignee: string | null;
  resolution_note: string | null;
  transport_chain_type?: string;
  destination_location?: string;
}

export interface AlertSummary {
  by_status: Record<string, number>;
  open_by_severity: Record<string, number>;
}

export interface MilestoneRow {
  code: string;
  leg_id: string | null;
  planned_ts: string;
  actual_ts: string | null;
  event_source: string | null;
  deviation: "MISSING" | "LATE" | "ON_TIME";
}

export interface OutboxRow {
  id: number;
  subscription_id: number;
  event_type: string;
  shipment_id: string;
  subject: string;
  body: string;
  channel: string;
  created_ts: string;
  sent_ts: string | null;
  subscriber_email: string;
}

export interface TrackLeg {
  leg_id: string;
  mode: string;
  color: string;
  origin: string;
  destination: string;
  coords: { lat: number; lon: number }[];
}

export interface OpsClockState {
  sim_now: string;
  speed: number;
  running: number;
  last_tick_ts: string;
}

export const api = {
  overview: () => getJson<OverviewPayload>("/api/analytics/overview"),
  trends: () => getJson<TrendsPayload>("/api/analytics/trends"),
  network: () => getJson<NetworkPayload>("/api/analytics/network"),
  shipments: (chain?: string, status?: string) =>
    getJson<ShipmentListItem[]>(
      `/api/shipments?limit=60${chain ? `&chain=${chain}` : ""}${status ? `&status=${status}` : ""}`
    ),
  trace: (id: string) => getJson<TracePayload>(`/api/shipments/${id}/trace`),
  sankey: () => getJson<SankeyPayload>("/api/shipments/flows/sankey?min_legs=100"),
  milestones: (id: string) =>
    getJson<{ shipment_id: string; milestones: MilestoneRow[] }>(
      `/api/shipments/${id}/milestones`
    ),
  posture: () =>
    getJson<{ pins: { alert_id: string; shipment_id: string; severity: string; title: string; lat: number; lon: number; location: string }[]; count: number }>(
      "/api/analytics/posture"
    ),
  eta: (id: string) =>
    getJson<{
      shipment_id: string;
      legs: { leg_sequence: number; transport_mode: string; lane: string; at_risk: boolean; eta_minutes_from_booking: Record<string, number> }[];
      eta_end_to_end_min: number;
      eta_end_to_end_bands_min: Record<string, number>;
      at_risk: boolean;
      method: string;
    }>(`/api/orders/${id}/eta`),
  tracks: (id: string) =>
    getJson<{ shipment_id: string; tracks: TrackLeg[] }>(`/api/shipments/${id}/tracks`),
  alerts: (status?: string, severity?: string) =>
    getJson<AlertItem[]>(
      `/api/alerts?limit=200${status ? `&status=${status}` : ""}${severity ? `&severity=${severity}` : ""}`
    ),
  alertSummary: () => getJson<AlertSummary>("/api/alerts/summary"),
  syncAlerts: () =>
    fetch(`${API_BASE}/api/alerts/sync`, { method: "POST" }).then((r) => r.json()),
  transitionAlert: (id: string, to: string, note?: string, assignee?: string) =>
    fetch(`${API_BASE}/api/alerts/${id}/transition`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ to, note, assignee }),
    }).then(async (r) => {
      if (!r.ok) throw new Error((await r.json()).detail ?? String(r.status));
      return r.json();
    }),
  subscribe: (email: string, shipmentId: string) =>
    fetch(`${API_BASE}/api/notifications/subscriptions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email,
        shipment_id: shipmentId,
        notify_on: "ALERT,DELAY,MISSING",
        delay_threshold_min: 120,
        channel: "email",
      }),
    }).then(async (r) => {
      if (!r.ok) throw new Error((await r.json()).detail ?? String(r.status));
      return r.json();
    }),
  outbox: () => getJson<OutboxRow[]>("/api/notifications/outbox?limit=50"),
  dispatchNotifications: () =>
    fetch(`${API_BASE}/api/notifications/dispatch`, { method: "POST" }).then((r) => r.json()),
  opsClock: () => getJson<OpsClockState>("/api/ops/clock"),
  opsClockStart: (speed: number, simNow?: string) =>
    fetch(`${API_BASE}/api/ops/clock/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ speed, sim_now: simNow }),
    }).then((r) => r.json()),
  opsClockStop: () =>
    fetch(`${API_BASE}/api/ops/clock/stop`, { method: "POST" }).then((r) => r.json()),
};
