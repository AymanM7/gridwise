"use client";

import { useMemo } from "react";
import {
  Area,
  Bar,
  Cell,
  ComposedChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipProps,
} from "recharts";
import type { ForecastHour } from "../lib/types";
import { LEVEL_COLOR, LEVEL_TEXT, dayHourLabel, gw, hourLabel, localHour, pct, shortDay } from "../lib/format";
import { axisProps } from "./ui";

interface Row extends ForecastHour {
  band: [number, number] | null;
  hl: boolean;
}

function TipBox({ active, payload }: TooltipProps<number, string>) {
  if (!active || !payload?.length) return null;
  const h = payload[0].payload as Row;
  return (
    <div className="rounded-xl border border-line bg-panel-2 p-3 text-xs shadow-xl">
      <div className="mb-1 font-semibold text-text">{dayHourLabel(h.target_ts)}</div>
      <div className="flex items-center gap-1.5">
        <span className="h-2 w-2 rounded-sm" style={{ background: LEVEL_COLOR[h.level] }} />
        {LEVEL_TEXT[h.level]} · strain <span className="tabular">{Math.round(h.strain_index)}</span>
      </div>
      <div className="tabular mt-1 text-muted">
        Net load {gw(h.net_load_mw)} · band {gw(h.band_low_mw)}–{gw(h.band_high_mw)}
      </div>
      <div className="tabular text-muted">Spike risk {pct(h.spike_prob)}</div>
      {h.low_confidence && <div className="mt-1 text-amber-300">⚠️ Uncertain: weather forecast is shifting</div>}
      <div className="mt-1 text-sky-300">Tap for “Why?”</div>
    </div>
  );
}

export default function StrainTimeline({
  hours,
  selected,
  onSelect,
  highlight,
}: {
  hours: ForecastHour[];
  selected: string | null;
  onSelect: (ts: string) => void;
  highlight: string[];
}) {
  const hlSet = useMemo(() => new Set(highlight.map((t) => new Date(t).getTime())), [highlight]);
  const rows: Row[] = useMemo(
    () =>
      hours.map((h) => ({
        ...h,
        band: h.band_low_mw != null && h.band_high_mw != null ? [h.band_low_mw, h.band_high_mw] : null,
        hl: hlSet.has(new Date(h.target_ts).getTime()),
      })),
    [hours, hlSet],
  );
  const ticks = rows.filter((r) => localHour(r.target_ts) % 6 === 0).map((r) => r.target_ts);
  const midnights = rows.filter((r) => localHour(r.target_ts) === 0).map((r) => r.target_ts);
  const lo = Math.min(...rows.map((r) => r.band_low_mw ?? r.net_load_mw ?? Infinity));
  const hi = Math.max(...rows.map((r) => r.band_high_mw ?? r.net_load_mw ?? -Infinity));
  const domain: [number, number] = [Math.floor((lo * 0.92) / 5000) * 5000, Math.ceil((hi * 1.02) / 5000) * 5000];
  const yTicks: number[] = [];
  for (let v = domain[0]; v <= domain[1]; v += 5000) yTicks.push(v);
  const anyHl = hlSet.size > 0;

  return (
    <div className="space-y-3">
      {/* Strip: one tappable cell per hour (keyboard + screen-reader friendly). */}
      <div className="overflow-x-auto pb-1">
        <div className="grid min-w-[560px] grid-cols-[repeat(48,minmax(0,1fr))] gap-[3px]" role="listbox" aria-label="Hourly strain, next 48 hours">
          {rows.map((r) => {
            const isSel = selected != null && new Date(selected).getTime() === new Date(r.target_ts).getTime();
            return (
              <button
                key={r.target_ts}
                role="option"
                aria-selected={isSel}
                aria-label={`${dayHourLabel(r.target_ts)}: ${LEVEL_TEXT[r.level]}, strain ${Math.round(r.strain_index)}, spike risk ${pct(r.spike_prob)}${r.hl ? ", suggested" : ""}`}
                onClick={() => onSelect(r.target_ts)}
                className={`relative h-9 rounded-[4px] transition-transform hover:scale-y-110 ${isSel ? "ring-2 ring-white" : r.hl ? "ring-2 ring-sky-400" : ""}`}
                style={{ background: LEVEL_COLOR[r.level], opacity: anyHl && !r.hl && !isSel ? 0.45 : 1 }}
              >
                {r.low_confidence && <span className="absolute -top-1 right-0 text-[9px]" aria-hidden>⚠</span>}
              </button>
            );
          })}
        </div>
        <div className="mt-1 grid min-w-[560px] grid-cols-[repeat(48,minmax(0,1fr))] text-[10px] text-muted">
          {rows.map((r) => (
            <div key={r.target_ts} className="whitespace-nowrap">
              {localHour(r.target_ts) === 0 ? <b className="text-text">{shortDay(r.target_ts)}</b> : localHour(r.target_ts) % 6 === 0 ? hourLabel(r.target_ts) : ""}
            </div>
          ))}
        </div>
      </div>

      {/* Chart: net load bars colored by level, shaded P10–P90 band. */}
      <div className="h-64 w-full sm:h-72">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: -8 }}>
            <XAxis dataKey="target_ts" ticks={ticks} tickFormatter={hourLabel} {...axisProps} />
            <YAxis
              domain={domain}
              allowDataOverflow
              ticks={yTicks.length <= 8 ? yTicks : yTicks.filter((_, i) => i % 2 === 0)}
              tickFormatter={(v: number) => `${(v / 1000).toFixed(0)} GW`}
              width={56}
              {...axisProps}
            />
            <Tooltip content={<TipBox />} cursor={{ fill: "#ffffff10" }} />
            {midnights.map((m) => (
              <ReferenceLine key={m} x={m} stroke="#3a3f48" strokeDasharray="3 3" />
            ))}
            <Area
              dataKey="band"
              type="monotone"
              stroke="none"
              fill="#9aa1ac"
              fillOpacity={0.18}
              isAnimationActive={false}
              name="P10–P90 band"
            />
            <Bar
              dataKey="net_load_mw"
              name="Net load"
              radius={[3, 3, 0, 0]}
              onClick={(d: unknown) => {
                const p = (d as { payload?: Row })?.payload;
                if (p) onSelect(p.target_ts);
              }}
              className="cursor-pointer"
              isAnimationActive={false}
            >
              {rows.map((r) => {
                const isSel = selected != null && new Date(selected).getTime() === new Date(r.target_ts).getTime();
                return (
                  <Cell
                    key={r.target_ts}
                    fill={LEVEL_COLOR[r.level]}
                    fillOpacity={anyHl && !r.hl && !isSel ? 0.35 : 0.9}
                    stroke={isSel ? "#ffffff" : r.hl ? "#38bdf8" : "none"}
                    strokeWidth={isSel || r.hl ? 2 : 0}
                  />
                );
              })}
            </Bar>
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
        {(["green", "yellow", "red"] as const).map((l) => (
          <span key={l} className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: LEVEL_COLOR[l] }} />
            {LEVEL_TEXT[l]} {l === "green" ? "(<60)" : l === "yellow" ? "(60–85)" : "(>85)"}
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-4 rounded-sm bg-[#9aa1ac]/30" /> P10–P90 band (how sure we are)
        </span>
        {anyHl && (
          <span className="inline-flex items-center gap-1.5 text-sky-300">
            <span className="h-2.5 w-2.5 rounded-sm ring-2 ring-sky-400" /> Suggested by chat
          </span>
        )}
      </div>
    </div>
  );
}
