// Types mirror the binding API contract (base path /api). Keep in sync with backend/.

export type Level = "green" | "yellow" | "red";

export interface Health {
  status: string;
  forecast_run_ts: string | null;
  forecast_age_minutes: number | null;
  data_source: string;
}

export interface ForecastHour {
  target_ts: string;
  local_time: string;
  horizon_h: number;
  net_load_mw: number | null;
  demand_mw: number | null;
  band_low_mw: number | null;
  band_high_mw: number | null;
  strain_index: number;
  level: Level;
  spike_prob: number | null;
  low_confidence: boolean;
  strain_source: string;
  wind_fcst_mw: number | null;
  solar_fcst_mw: number | null;
}

export interface Window {
  start_local: string;
  end_local: string;
  label: string;
}

export interface BestWindow extends Window {
  avg_strain: number;
}

export interface AvoidWindow extends Window {
  max_spike_prob: number;
}

export interface Forecast {
  run_ts: string;
  hours: ForecastHour[];
  summary: {
    peak: { local_time: string; net_load_mw: number; strain_index: number; level: Level };
    max_spike: { local_time: string; spike_prob: number };
    level_counts: Record<Level, number>;
    best_windows: BestWindow[];
    avoid_windows: AvoidWindow[];
    verdict: string;
  };
}

export interface Driver {
  rank: number;
  feature: string;
  label: string;
  value: number | null;
  mw: number | null;
  direction: "raises" | "lowers" | string;
}

export interface Drivers {
  target_ts: string;
  local_time: string;
  level: Level;
  strain_index: number;
  drivers: Driver[];
  why_red: string | null;
}

export interface Tip {
  icon: string;
  text: string;
  window: string | null;
}

export interface Advice {
  date_local: string;
  generated_by: "gemini" | "rules";
  headline: string;
  tips: Tip[];
  best_hours: string[];
  avoid_hours: string[];
  why_red: Record<string, string>;
}

export interface HistoryDay {
  day: string;
  peak_net_load_mw: number | null;
  max_strain: number | null;
  avg_price: number | null;
  max_price: number | null;
  spike_hours: number;
}

export interface History {
  daily: HistoryDay[];
}

export interface SimParams {
  pct: number;
  kwh: number;
  from: string;
  to: string;
}

export interface SimStats {
  red_hours: number;
  peak_mw: number;
  max_spike_prob: number;
}

export interface SimPoint {
  target_ts: string;
  local_time: string;
  before_mw: number;
  after_mw: number;
  level_before: Level;
  level_after: Level;
  spike_before: number;
  spike_after: number;
}

export interface Simulation {
  params: SimParams;
  nearest_params: SimParams;
  before: SimStats;
  after: SimStats;
  peak_reduction_mw: number;
  peakers_avoided: number;
  curve: SimPoint[];
  /** Set only by the offline (fixtures) estimator; never sent by the API. */
  estimated?: boolean;
}

export interface ReportRow {
  date: string;
  source: "live" | "backtest" | string;
  mape: number | null;
  demand_mape: number | null;
  spike_recall: number | null;
  band_coverage: number | null;
  spike_hours_caught: number;
  spike_hours_actual: number;
}

export interface ReportCard {
  latest: ReportRow | null;
  rows: ReportRow[];
  note: string | null;
}

export interface ChatAnswer {
  answer: string;
  highlight_hours: string[];
}
