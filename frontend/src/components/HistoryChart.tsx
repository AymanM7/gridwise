"use client";

import { Bar, Cell, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { History, HistoryDay } from "../lib/types";
import { LEVEL_COLOR, LEVEL_TEXT, levelOf, shortDay } from "../lib/format";
import { Empty, axisProps } from "./ui";
import { ACCENT, LegendChip, MUTED, TooltipRow, TooltipShell } from "./insights/shared";

function HistoryTooltip({ active, payload }: { active?: boolean; payload?: { payload: HistoryDay }[] }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  const lvl = levelOf(d.max_strain ?? 0);
  return (
    <TooltipShell title={shortDay(d.day)}>
      <TooltipRow
        swatch={<span className="h-2.5 w-1.5 rounded-[2px]" style={{ background: LEVEL_COLOR[lvl] }} />}
        label="Peak net load"
        value={d.peak_net_load_mw == null ? "–" : `${(d.peak_net_load_mw / 1000).toFixed(1)} GW`}
      />
      <TooltipRow
        swatch={<span className="h-1.5 w-1.5 rounded-full" style={{ background: LEVEL_COLOR[lvl] }} />}
        label="Max strain"
        value={d.max_strain == null ? "–" : `${Math.round(d.max_strain)} · ${LEVEL_TEXT[lvl]}`}
      />
      <TooltipRow
        swatch={<span className="h-0.5 w-3 rounded-full" style={{ background: ACCENT }} />}
        label="Max price"
        value={d.max_price == null ? "–" : `$${d.max_price.toFixed(0)}/MWh`}
      />
      {d.spike_hours > 0 && (
        <div className="mt-1 border-t border-line pt-1 text-muted">
          {d.spike_hours} price-spike hour{d.spike_hours === 1 ? "" : "s"}
        </div>
      )}
    </TooltipShell>
  );
}

export default function HistoryChart({ history }: { history: History }) {
  const rows = history.daily;
  if (!rows.length) return <Empty>No history yet.</Empty>;
  const spikeDays = rows.filter((r) => r.spike_hours > 0).length;
  return (
    <div className="space-y-4">
      <p className="text-sm leading-relaxed text-muted">
        Daily peak net load and max real-time price.{" "}
        <span className="tabular font-medium text-text">
          {spikeDays} of the last {rows.length} days
        </span>{" "}
        had price spikes.
      </p>
      <div className="flex flex-wrap gap-1.5">
        <LegendChip color={LEVEL_COLOR.green} label="Normal" shape="bar" />
        <LegendChip color={LEVEL_COLOR.yellow} label="Elevated" shape="bar" />
        <LegendChip color={LEVEL_COLOR.red} label="Tight" shape="bar" />
        <LegendChip color={ACCENT} label="Max price" shape="line" />
        <LegendChip color={MUTED} label="$100 spike line" shape="dash" />
      </div>
      <div className="h-60 w-full sm:h-64">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 8, right: 0, bottom: 0, left: -8 }} barCategoryGap="22%">
            <XAxis dataKey="day" tickFormatter={(d: string) => shortDay(d).replace(/^\w+, /, "")} minTickGap={24} {...axisProps} />
            <YAxis
              yAxisId="mw"
              tickFormatter={(v: number) => `${(v / 1000).toFixed(0)} GW`}
              width={52}
              {...axisProps}
            />
            <YAxis yAxisId="usd" orientation="right" tickFormatter={(v: number) => `$${v}`} width={44} {...axisProps} />
            <ReferenceLine yAxisId="usd" y={100} stroke={MUTED} strokeOpacity={0.6} strokeDasharray="3 4" />
            <Tooltip content={<HistoryTooltip />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
            <Bar
              yAxisId="mw"
              dataKey="peak_net_load_mw"
              name="Peak net load"
              radius={[4, 4, 0, 0]}
              maxBarSize={18}
              isAnimationActive={false}
            >
              {rows.map((r) => (
                <Cell key={r.day} fill={LEVEL_COLOR[levelOf(r.max_strain ?? 0)]} fillOpacity={0.8} />
              ))}
            </Bar>
            <Line
              yAxisId="usd"
              dataKey="max_price"
              name="Max price"
              type="monotone"
              stroke={ACCENT}
              strokeWidth={1.75}
              dot={false}
              activeDot={{ r: 3.5, fill: ACCENT, stroke: "#07080a", strokeWidth: 2 }}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
