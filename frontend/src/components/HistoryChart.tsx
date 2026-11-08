"use client";

import { Bar, Cell, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { History } from "../lib/types";
import { LEVEL_COLOR, levelOf, shortDay } from "../lib/format";
import { Empty, axisProps, tooltipStyle } from "./ui";

export default function HistoryChart({ history }: { history: History }) {
  const rows = history.daily;
  if (!rows.length) return <Empty>No history yet.</Empty>;
  const spikeDays = rows.filter((r) => r.spike_hours > 0).length;
  return (
    <div className="space-y-2">
      <p className="text-sm text-muted">
        Daily peak net load (bars, colored by that day&apos;s max strain) and max real-time price (line). {spikeDays} of the last{" "}
        {rows.length} days had price spikes.
      </p>
      <div className="h-56 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 8, right: 0, bottom: 0, left: -8 }}>
            <XAxis dataKey="day" tickFormatter={(d: string) => shortDay(d).replace(/^\w+, /, "")} minTickGap={24} {...axisProps} />
            <YAxis
              yAxisId="mw"
              tickFormatter={(v: number) => `${(v / 1000).toFixed(0)} GW`}
              width={52}
              {...axisProps}
            />
            <YAxis yAxisId="usd" orientation="right" tickFormatter={(v: number) => `$${v}`} width={44} {...axisProps} />
            <ReferenceLine yAxisId="usd" y={100} stroke="#ef4444" strokeDasharray="4 4" />
            <Tooltip
              {...tooltipStyle}
              labelFormatter={(l) => shortDay(String(l))}
              formatter={(v: number, name: string) =>
                name === "Peak net load" ? [`${(v / 1000).toFixed(1)} GW`, name] : [`$${v.toFixed(0)}/MWh`, name]
              }
            />
            <Bar yAxisId="mw" dataKey="peak_net_load_mw" name="Peak net load" radius={[3, 3, 0, 0]} isAnimationActive={false}>
              {rows.map((r) => (
                <Cell key={r.day} fill={LEVEL_COLOR[levelOf(r.max_strain ?? 0)]} fillOpacity={0.75} />
              ))}
            </Bar>
            <Line yAxisId="usd" dataKey="max_price" name="Max price" stroke="#e8eaed" strokeWidth={1.5} dot={false} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
