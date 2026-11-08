"use client";

import { useEffect, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fetchSimulation } from "../lib/api";
import type { Forecast, SimParams } from "../lib/types";
import { LEVEL_COLOR, dayHourLabel, gw, hourLabel, localHour, pct } from "../lib/format";
import { PEAKER_MW } from "../lib/simulate";
import { Badge, ErrorBox, Loading, axisProps, tooltipStyle } from "./ui";

function HeroStat({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: string }) {
  return (
    <div className="rounded-xl border border-line bg-panel-2 p-3 sm:p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-muted">{label}</div>
      <div className="tabular mt-1 text-3xl font-bold sm:text-4xl" style={tone ? { color: tone } : undefined}>
        {value}
      </div>
      {sub && <div className="mt-1 text-xs text-muted">{sub}</div>}
    </div>
  );
}

// Options mirror the precomputed scenario grid in gold.shift_scenarios (08_ripple), so the live API
// answers with the exact scenario instead of snapping to a "closest" one.
const FROM_OPTIONS = [
  { v: "16-20", l: "4–8 pm" },
  { v: "17-21", l: "5–9 pm" },
];
const TO_OPTIONS = [
  { v: "10-14", l: "10 am–2 pm (solar hours)" },
  { v: "22-02", l: "10 pm–2 am" },
  { v: "00-04", l: "12–4 am" },
];
const PCT_STEPS = [1, 2, 5, 10, 15, 20, 25];
const KWH_STEPS = [1, 2, 3, 5, 8];
/** Demo default: a scenario that visibly helps (≈ −1.7 GW, ~17 peakers on the 2026-11-07 run). 15% is
 *  the efficient point: past it the peak moves into the next evening hour and the cut saturates. */
export const DEFAULT_SIM: SimParams = { pct: 15, kwh: 5, from: "17-21", to: "10-14" };

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

function label(opts: { v: string; l: string }[], v: string) {
  return opts.find((o) => o.v === v)?.l ?? v;
}

export default function RipplePanel({ forecast }: { forecast?: Forecast }) {
  const [p, setP] = useState<SimParams>(DEFAULT_SIM);
  const dp = useDebounced(p, 250);
  const q = useQuery({
    queryKey: ["simulate", dp, forecast?.run_ts],
    queryFn: () => fetchSimulation(dp, forecast),
    placeholderData: keepPreviousData,
  });
  const s = q.data?.data;
  const np = s?.nearest_params;
  const snapped = np && (np.pct !== dp.pct || np.kwh !== dp.kwh || np.from !== dp.from || np.to !== dp.to);
  // Biggest single-hour cut. The 48 h peak can sit in an evening the scenario can't shift (it's already
  // under way when the forecast starts), so the headline falls back to this when the peak doesn't move.
  const cut = s?.curve.reduce(
    (best, c) => (c.before_mw - c.after_mw > best.mw ? { mw: c.before_mw - c.after_mw, ts: c.target_ts } : best),
    { mw: 0, ts: "" },
  );
  const peakMoved = !!s && s.peak_reduction_mw >= 50;
  const rebound = !!s && s.peak_reduction_mw < -50;
  const showPeak = peakMoved || rebound || !cut || cut.mw < 50;
  // Peakers follow whichever MW figure is the headline, so the two hero stats never contradict.
  const heroPeakers = !s ? 0 : showPeak ? s.peakers_avoided : Math.round((cut?.mw ?? 0) / PEAKER_MW);
  const spikeChanged = !!s && Math.abs(s.before.max_spike_prob - s.after.max_spike_prob) >= 0.005;
  const redChanged = !!s && s.before.red_hours !== s.after.red_hours;
  const ticks = s?.curve.filter((c) => localHour(c.target_ts) % 6 === 0).map((c) => c.target_ts) ?? [];

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">What if Texas homes moved some evening usage (laundry, dishwasher, EV charging) out of the evening peak? Small actions add up.</p>
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block text-sm">
          <span className="flex justify-between">
            Homes participating <b className="tabular">{p.pct}%</b>
          </span>
          <input
            type="range"
            min={0}
            max={PCT_STEPS.length - 1}
            step={1}
            value={Math.max(0, PCT_STEPS.indexOf(p.pct))}
            onChange={(e) => setP({ ...p, pct: PCT_STEPS[Number(e.target.value)] })}
            className="mt-2 w-full"
            aria-valuetext={`${p.pct} percent of homes`}
          />
        </label>
        <label className="block text-sm">
          <span className="flex justify-between">
            kWh shifted per home <b className="tabular">{p.kwh} kWh</b>
          </span>
          <input
            type="range"
            min={0}
            max={KWH_STEPS.length - 1}
            step={1}
            value={Math.max(0, KWH_STEPS.indexOf(p.kwh))}
            onChange={(e) => setP({ ...p, kwh: KWH_STEPS[Number(e.target.value)] })}
            className="mt-2 w-full"
            aria-valuetext={`${p.kwh} kilowatt hours`}
          />
        </label>
        <label className="block text-sm">
          From
          <select
            value={p.from}
            onChange={(e) => setP({ ...p, from: e.target.value })}
            className="mt-1 w-full rounded-lg border border-line bg-panel-2 px-3 py-2"
          >
            {FROM_OPTIONS.map((o) => (
              <option key={o.v} value={o.v}>
                {o.l}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          To
          <select
            value={p.to}
            onChange={(e) => setP({ ...p, to: e.target.value })}
            className="mt-1 w-full rounded-lg border border-line bg-panel-2 px-3 py-2"
          >
            {TO_OPTIONS.map((o) => (
              <option key={o.v} value={o.v}>
                {o.l}
              </option>
            ))}
          </select>
        </label>
      </div>

      {q.isLoading ? (
        <Loading label="Running scenario" className="h-56" />
      ) : q.isError ? (
        <ErrorBox message={`Couldn't run the scenario: ${(q.error as Error).message}`} onRetry={() => q.refetch()} />
      ) : s ? (
        <div className={`space-y-3 transition-opacity ${q.isFetching ? "opacity-70" : ""}`}>
          <div className="flex flex-wrap gap-2">
            {s.estimated && <Badge tone="warn">Offline estimate · live API re-runs the spike model</Badge>}
            {snapped && np && (
              <Badge>
                Closest precomputed scenario: {np.pct}% · {np.kwh} kWh · {label(FROM_OPTIONS, np.from)} → {label(TO_OPTIONS, np.to)}
              </Badge>
            )}
          </div>
          <div className="grid grid-cols-2 gap-2">
            {showPeak ? (
              <HeroStat
                label="Peak cut"
                value={rebound ? `+${gw(-s.peak_reduction_mw)}` : `−${gw(Math.max(0, s.peak_reduction_mw))}`}
                sub={`48 h peak ${gw(s.before.peak_mw)} → ${gw(s.after.peak_mw)}${rebound ? " · new peak in the later window" : ""}`}
                tone={rebound ? LEVEL_COLOR.red : LEVEL_COLOR.green}
              />
            ) : (
              <HeroStat
                label="Evening load cut"
                value={`−${gw(cut!.mw)}`}
                sub={`at ${dayHourLabel(cut!.ts)} · the 48 h peak (${gw(s.before.peak_mw)}) falls before the window`}
                tone={LEVEL_COLOR.green}
              />
            )}
            <HeroStat
              label="Gas peakers avoided"
              value={`≈ ${heroPeakers}`}
              sub="~100 MW plants that wouldn't need to fire"
              tone={heroPeakers > 0 ? LEVEL_COLOR.green : undefined}
            />
          </div>
          {(spikeChanged || redChanged) && (
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
              {spikeChanged && (
                <span className="tabular">
                  Max spike risk {pct(s.before.max_spike_prob)} → {pct(s.after.max_spike_prob)}
                </span>
              )}
              {redChanged && (
                <span
                  className="tabular"
                  style={{ color: s.after.red_hours < s.before.red_hours ? LEVEL_COLOR.green : LEVEL_COLOR.yellow }}
                >
                  Red hours {s.before.red_hours} → {s.after.red_hours}
                  {s.after.red_hours > s.before.red_hours ? " (the later window gets busier)" : ""}
                </span>
              )}
            </div>
          )}
          <div className="h-56 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={s.curve} margin={{ top: 8, right: 8, bottom: 0, left: -8 }}>
                <XAxis dataKey="target_ts" ticks={ticks} tickFormatter={hourLabel} {...axisProps} />
                <YAxis
                  domain={["auto", "auto"]}
                  tickFormatter={(v: number) => `${(v / 1000).toFixed(0)} GW`}
                  width={56}
                  {...axisProps}
                />
                <Tooltip
                  {...tooltipStyle}
                  labelFormatter={(l) => dayHourLabel(String(l))}
                  formatter={(v: number, n: string) => [gw(v, 2), n]}
                />
                <Legend wrapperStyle={{ fontSize: 12, color: "#9aa1ac" }} />
                <Line dataKey="before_mw" name="Before" stroke="#9aa1ac" strokeDasharray="4 3" dot={false} isAnimationActive={false} />
                <Line dataKey="after_mw" name="After shift" stroke="#38bdf8" strokeWidth={2} dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      ) : null}
    </div>
  );
}
