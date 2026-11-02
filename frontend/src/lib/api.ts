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

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
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
};
