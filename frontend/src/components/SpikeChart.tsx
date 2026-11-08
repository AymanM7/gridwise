"use client";

import { Area, AreaChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ForecastHour } from "../lib/types";
import { dayHourLabel, hourLabel, localHour, pct } from "../lib/format";
import { axisProps, tooltipStyle } from "./ui";

export default function SpikeChart({ hours, onSelect }: { hours: ForecastHour[]; onSelect: (ts: string) => void }) {
  const rows = hours.map((h) => ({ target_ts: h.target_ts, p: Math.round((h.spike_prob ?? 0) * 1000) / 10 }));
  const ticks = rows.filter((r) => localHour(r.target_ts) % 6 === 0).map((r) => r.target_ts);
  const max = hours.reduce((m, h) => ((h.spike_prob ?? 0) > (m.spike_prob ?? 0) ? h : m), hours[0]);
  return (
    <div>
      <p className="mb-2 text-sm text-muted">
        Chance each hour that wholesale prices jump above <b className="text-text">$100/MWh</b>. Highest:{" "}
        <b className="tabular text-text">{pct(max?.spike_prob)}</b> at {max ? dayHourLabel(max.target_ts) : "–"}.
      </p>
      <div className="h-44 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart
            data={rows}
            margin={{ top: 8, right: 8, bottom: 0, left: -8 }}
            onClick={(e: unknown) => {
              const ts = (e as { activeLabel?: string })?.activeLabel;
              if (ts) onSelect(ts);
            }}
          >
            <defs>
              <linearGradient id="spikeFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#ef4444" stopOpacity={0.6} />
                <stop offset="100%" stopColor="#ef4444" stopOpacity={0.05} />
              </linearGradient>
            </defs>
            <XAxis dataKey="target_ts" ticks={ticks} tickFormatter={hourLabel} {...axisProps} />
            <YAxis domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tickFormatter={(v: number) => `${v}%`} width={44} {...axisProps} />
            <ReferenceLine y={50} stroke="#eab308" strokeDasharray="4 4" label={{ value: "50%", fill: "#eab308", fontSize: 10, position: "right" }} />
            <Tooltip
              {...tooltipStyle}
              labelFormatter={(l) => dayHourLabel(String(l))}
              formatter={(v: number) => [`${v}%`, "Spike risk"]}
            />
            <Area type="monotone" dataKey="p" stroke="#ef4444" strokeWidth={2} fill="url(#spikeFill)" isAnimationActive={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
