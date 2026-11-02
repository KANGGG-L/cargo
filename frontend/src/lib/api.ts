export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export interface OverviewKpis {
  air_otp_pct: number;
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

export interface TrendsPayload {
  daily: TrendPoint[];
  monthly: MonthlyPoint[];
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

export interface NetworkPayload {
  mode_split: ModeSplit[];
  chain_mix: ChainMix[];
  air_lanes: AirLane[];
  feeder_ports: FeederPort[];
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json() as Promise<T>;
}

export const api = {
  overview: () => getJson<OverviewPayload>("/api/analytics/overview"),
  trends: () => getJson<TrendsPayload>("/api/analytics/trends"),
  network: () => getJson<NetworkPayload>("/api/analytics/network"),
};
