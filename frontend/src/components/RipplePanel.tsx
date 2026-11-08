"use client";

import { useEffect, useId, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Area, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Activity, Factory, Flame, LoaderCircle, TrendingDown } from "lucide-react";
import { fetchSimulation } from "../lib/api";
import { RippleField } from "./shader/Backgrounds";
import type { Forecast, SimParams, SimPoint } from "../lib/types";
import { LEVEL_COLOR, dayHourLabel, gw, hourLabel, localHour, pct } from "../lib/format";
import { PEAKER_MW } from "../lib/simulate";
import { ErrorBox, Loading, axisProps } from "./ui";
import { ACCENT, Chip, LegendChip, MUTED, StatTile, TooltipRow, TooltipShell } from "./insights/shared";
import { Segmented, StepSlider } from "./insights/controls";

// Options mirror the precomputed scenario grid in gold.shift_scenarios (08_ripple), so the live API
// answers with the exact scenario instead of snapping to a "closest" one.
const FROM_OPTIONS = [
  { v: "16-20", l: "4–8 pm" },
  { v: "17-21", l: "5–9 pm" },
];
const TO_OPTIONS = [
  { v: "10-14", l: "10 am–2 pm", hint: "solar hours" },
  { v: "22-02", l: "10 pm–2 am", hint: "late night" },
  { v: "00-04", l: "12–4 am", hint: "overnight" },
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

const fmtGw = (n: number) => `${(n / 1000).toFixed(1)} GW`;

function RippleTooltip({ active, payload }: { active?: boolean; payload?: { payload: SimPoint }[] }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  const d = p.before_mw - p.after_mw;
  return (
    <TooltipShell title={dayHourLabel(p.target_ts)}>
      <TooltipRow
        swatch={<span className="w-3 border-t border-dashed" style={{ borderColor: MUTED }} />}
        label="Before"
        value={gw(p.before_mw, 2)}
      />
      <TooltipRow
        swatch={<span className="h-0.5 w-3 rounded-full" style={{ background: ACCENT }} />}
        label="After shift"
        value={gw(p.after_mw, 2)}
      />
      {Math.abs(d) >= 1 && (
        <div className="mt-1 border-t border-line pt-1 text-right tabular text-muted">
          {d > 0 ? "−" : "+"}
          {Math.abs(d).toFixed(0)} MW
        </div>
      )}
    </TooltipShell>
  );
}

export default function RipplePanel({ forecast }: { forecast?: Forecast }) {
  const [p, setP] = useState<SimParams>(DEFAULT_SIM);
  const dp = useDebounced(p, 250);
  const gradId = useId().replace(/:/g, "");
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
  const ticks = s?.curve.filter((c) => localHour(c.target_ts) % 6 === 0).map((c) => c.target_ts) ?? [];
  const updating = q.isFetching || p !== dp;

  // Headline MW figure (always non-negative for the tween; sign is in the formatter).
  const headMw = !s ? 0 : showPeak ? (rebound ? -s.peak_reduction_mw : Math.max(0, s.peak_reduction_mw)) : (cut?.mw ?? 0);
  const fromL = label(FROM_OPTIONS, dp.from);
  const toL = label(TO_OPTIONS, dp.to);
  const summary = !s
    ? ""
    : rebound
      ? `If ${dp.pct}% of Texas homes moved ${dp.kwh} kWh from ${fromL} to ${toL}, the later window would become the new peak (+${gw(headMw)}), so a smaller shift works better here.`
      : headMw >= 50
        ? `If ${dp.pct}% of Texas homes moved ${dp.kwh} kWh each from ${fromL} to ${toL}, the ${showPeak ? "48-hour peak" : "evening load"} would drop by ${gw(headMw)}: about ${heroPeakers} gas peaker plant${heroPeakers === 1 ? "" : "s"} that wouldn't need to fire.`
        : `Moving ${dp.kwh} kWh from ${fromL} to ${toL} in ${dp.pct}% of homes barely moves the peak; try more homes or a bigger shift.`;

  return (
    <div className="space-y-6">
      {/* Ripple shader: rings spread faster and brighter as more homes participate.
          z-[-1] keeps it under the content but inside the card (.surface is a stacking context). */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 -z-[1] h-72 overflow-hidden rounded-t-[18px] [mask-image:linear-gradient(to_bottom,black_20%,transparent)]"
      >
        <RippleField amount={Math.min(1, p.pct / 25)} />
      </div>
      <p className="max-w-3xl text-sm leading-relaxed text-muted">
        What if Texas homes moved some evening usage (laundry, dishwasher, EV charging) out of the evening peak? Drag the
        sliders: small actions add up.
      </p>

      {/* Controls */}
      <div className="grid gap-x-8 gap-y-6 rounded-2xl border border-line bg-panel-2/30 p-4 sm:p-5 md:grid-cols-2">
        <StepSlider
          label="Homes participating"
          steps={PCT_STEPS}
          value={p.pct}
          onChange={(v) => setP({ ...p, pct: v })}
          format={(v) => `${v}%`}
          valueText={(v) => `${v} percent of homes`}
        />
        <StepSlider
          label="kWh shifted per home"
          steps={KWH_STEPS}
          value={p.kwh}
          onChange={(v) => setP({ ...p, kwh: v })}
          format={(v) => `${v} kWh`}
          valueText={(v) => `${v} kilowatt hours`}
        />
        <Segmented label="Move usage from" name="ripple-from" options={FROM_OPTIONS} value={p.from} onChange={(v) => setP({ ...p, from: v })} />
        <Segmented label="To" name="ripple-to" options={TO_OPTIONS} value={p.to} onChange={(v) => setP({ ...p, to: v })} />
      </div>

      {q.isPending ? (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="skeleton h-[112px] rounded-xl" aria-hidden />
            ))}
          </div>
          <Loading label="Running scenario" className="h-64" />
        </div>
      ) : q.isError ? (
        <ErrorBox message={`Couldn't run the scenario: ${(q.error as Error).message}`} onRetry={() => q.refetch()} />
      ) : s ? (
        <div className="space-y-5">
          {(s.estimated || snapped) && (
            <div className="flex flex-wrap items-center gap-2">
              {s.estimated && <Chip className="border-amber-400/30 text-amber-200">Offline estimate · live API re-runs the spike model</Chip>}
              {snapped && np && (
                <Chip>
                  Closest precomputed: {np.pct}% · {np.kwh} kWh · {label(FROM_OPTIONS, np.from)} → {label(TO_OPTIONS, np.to)}
                </Chip>
              )}
            </div>
          )}

          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile
              size="lg"
              icon={<TrendingDown />}
              label={showPeak ? "Peak cut" : "Evening load cut"}
              value={headMw}
              format={(n) => `${rebound ? "+" : "−"}${fmtGw(n)}`}
              tone={rebound ? LEVEL_COLOR.red : headMw >= 50 ? LEVEL_COLOR.green : undefined}
              sub={
                showPeak
                  ? `48 h peak ${gw(s.before.peak_mw)} → ${gw(s.after.peak_mw)}${rebound ? " · new peak in the later window" : ""}`
                  : `at ${dayHourLabel(cut!.ts)} · 48 h peak (${gw(s.before.peak_mw)}) falls before the window`
              }
            />
            <StatTile
              size="lg"
              icon={<Factory />}
              label="Gas peakers avoided"
              value={heroPeakers}
              format={(n) => `≈ ${Math.round(n)}`}
              tone={heroPeakers > 0 ? LEVEL_COLOR.green : undefined}
              sub="~100 MW plants that wouldn't need to fire"
            />
            <StatTile
              icon={<Flame />}
              label="Max spike risk"
              value={s.after.max_spike_prob * 100}
              format={(n) => `${Math.round(n)}%`}
              sub={
                <span className="tabular">
                  was {pct(s.before.max_spike_prob)}
                  {Math.abs(s.before.max_spike_prob - s.after.max_spike_prob) < 0.005 ? " · unchanged" : ""}
                </span>
              }
            />
            <StatTile
              icon={<Activity />}
              label="Red hours"
              value={s.after.red_hours}
              format={(n) => `${Math.round(n)}`}
              tone={
                s.after.red_hours < s.before.red_hours
                  ? LEVEL_COLOR.green
                  : s.after.red_hours > s.before.red_hours
                    ? LEVEL_COLOR.yellow
                    : undefined
              }
              sub={
                <span className="tabular">
                  was {s.before.red_hours}
                  {s.after.red_hours > s.before.red_hours ? " · later window busier" : s.after.red_hours === s.before.red_hours ? " · unchanged" : ""}
                </span>
              }
            />
          </div>

          <p className="border-l-2 border-accent/60 pl-3 text-sm leading-relaxed text-text/90 text-pretty">{summary}</p>

          <div>
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <span className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.14em] text-muted">
                Net load, next 48 h
                <span role="status" className={`inline-flex items-center gap-1 normal-case tracking-normal transition-opacity duration-200 ${updating ? "opacity-100" : "opacity-0"}`}>
                  <LoaderCircle aria-hidden className="h-3 w-3 animate-spin motion-reduce:animate-none" />
                  {updating ? "updating" : ""}
                </span>
              </span>
              <div className="flex flex-wrap gap-1.5">
                <LegendChip color={MUTED} label="Before" shape="dash" />
                <LegendChip color={ACCENT} label="After shift" shape="line" />
              </div>
            </div>
            <div className="h-60 w-full sm:h-72">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={s.curve} margin={{ top: 8, right: 4, bottom: 0, left: -8 }}>
                  <defs>
                    <linearGradient id={`ripple-${gradId}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={ACCENT} stopOpacity={0.28} />
                      <stop offset="100%" stopColor={ACCENT} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="target_ts" ticks={ticks} tickFormatter={hourLabel} {...axisProps} />
                  <YAxis
                    domain={["auto", "auto"]}
                    tickFormatter={(v: number) => `${(v / 1000).toFixed(0)} GW`}
                    width={52}
                    {...axisProps}
                  />
                  <Tooltip
                    content={<RippleTooltip />}
                    cursor={{ stroke: "rgba(255,255,255,0.15)", strokeWidth: 1 }}
                  />
                  <Area
                    dataKey="after_mw"
                    name="After shift"
                    type="monotone"
                    stroke={ACCENT}
                    strokeWidth={2}
                    fill={`url(#ripple-${gradId})`}
                    dot={false}
                    activeDot={{ r: 4, fill: ACCENT, stroke: "#07080a", strokeWidth: 2 }}
                    isAnimationActive
                    animationDuration={550}
                    animationEasing="ease-out"
                  />
                  <Line
                    dataKey="before_mw"
                    name="Before"
                    type="monotone"
                    stroke={MUTED}
                    strokeOpacity={0.8}
                    strokeWidth={1.25}
                    strokeDasharray="4 4"
                    dot={false}
                    activeDot={{ r: 3, fill: MUTED, stroke: "#07080a", strokeWidth: 2 }}
                    isAnimationActive={false}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
