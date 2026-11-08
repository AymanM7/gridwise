// Offline Ripple estimator, used ONLY in fixtures mode (or when /api/simulate is unreachable).
// The live API looks up precomputed scenarios that re-run Model B; this approximates them from the
// exported forecast + strain reference so the panel stays interactive without the backend.
import type { Forecast, Level, SimParams, Simulation, SimStats } from "./types";
import { levelOf, localHour } from "./format";

export interface RefPoint {
  month: number;
  pct: number;
  net_load_mw: number;
}

/** ERCOT serves roughly 10 million residential meters. */
export const TEXAS_HOMES = 10_000_000;
/** Typical gas peaker unit size used to translate MW into "plants not needed". */
export const PEAKER_MW = 100;

export function windowHours(spec: string): number[] {
  const [a, b] = spec.split("-").map(Number);
  const out: number[] = [];
  for (let h = a; h !== b; h = (h + 1) % 24) {
    out.push(h);
    if (out.length > 24) break;
  }
  return out;
}

function interp(x: number, xp: number[], fp: number[]): number {
  if (x <= xp[0]) return 0;
  if (x >= xp[xp.length - 1]) return 100;
  for (let i = 1; i < xp.length; i++) {
    if (x <= xp[i]) {
      const t = xp[i] === xp[i - 1] ? 0 : (x - xp[i - 1]) / (xp[i] - xp[i - 1]);
      return fp[i - 1] + t * (fp[i] - fp[i - 1]);
    }
  }
  return 100;
}

function strainFor(netLoad: number, month: number, spike: number, ref: RefPoint[]): number {
  const g = ref.filter((r) => r.month === month);
  if (!g.length) return 50;
  const xp: number[] = [];
  let run = -Infinity;
  for (const r of g) {
    run = Math.max(run, r.net_load_mw);
    xp.push(run);
  }
  const base = interp(netLoad, xp, g.map((r) => r.pct));
  return spike > 0.5 ? Math.min(100, base + 15) : base;
}

function monthOf(iso: string): number {
  return Number(new Intl.DateTimeFormat("en-US", { timeZone: "America/Chicago", month: "numeric" }).format(new Date(iso)));
}

export function estimateSimulation(fc: Forecast, ref: RefPoint[], p: SimParams): Simulation {
  const from = windowHours(p.from);
  const to = windowHours(p.to);
  const energyMwh = ((p.pct / 100) * TEXAS_HOMES * p.kwh) / 1000; // per day
  const cutMw = from.length ? energyMwh / from.length : 0;
  const addMw = to.length ? energyMwh / to.length : 0;

  const curve = fc.hours.map((h) => {
    const hr = localHour(h.target_ts);
    const before = h.net_load_mw ?? 0;
    const delta = from.includes(hr) ? -cutMw : to.includes(hr) ? addMw : 0;
    const after = before + delta;
    const sb = h.spike_prob ?? 0;
    // Spike odds respond to the scarcity margin; ~-8 percentage points per GW removed near the peak.
    const sa = Math.min(1, Math.max(0, sb + (delta / 1000) * 0.08 * (sb > 0.05 ? 1 : 0.2)));
    const month = monthOf(h.target_ts);
    const strainAfter = delta === 0 ? h.strain_index : strainFor(after, month, sa, ref);
    return {
      target_ts: h.target_ts,
      local_time: h.local_time,
      before_mw: before,
      after_mw: Math.round(after),
      level_before: h.level as Level,
      level_after: levelOf(strainAfter),
      spike_before: sb,
      spike_after: Number(sa.toFixed(4)),
    };
  });

  const stats = (k: "before" | "after"): SimStats => ({
    red_hours: curve.filter((c) => (k === "before" ? c.level_before : c.level_after) === "red").length,
    peak_mw: Math.max(...curve.map((c) => (k === "before" ? c.before_mw : c.after_mw))),
    max_spike_prob: Math.max(...curve.map((c) => (k === "before" ? c.spike_before : c.spike_after))),
  });
  const before = stats("before");
  const after = stats("after");
  const reduction = Math.max(0, before.peak_mw - after.peak_mw);
  return {
    params: p,
    nearest_params: p,
    before,
    after,
    peak_reduction_mw: Math.round(reduction),
    peakers_avoided: Math.round(reduction / PEAKER_MW),
    curve,
    estimated: true,
  };
}
