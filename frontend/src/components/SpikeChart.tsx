"use client";

import { Area, AreaChart, ReferenceDot, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis, type TooltipProps } from "recharts";
import type { ForecastHour } from "../lib/types";
import { dayHourLabel, hourLabel, localHour, pct } from "../lib/format";
import { AnimatedNumber, EASE_OUT, motion } from "./motion";
import { axisProps } from "./ui";

const RED = "#f43f5e";
const THRESHOLD = 50;

interface Row {
  target_ts: string;
  p: number;
}

function SpikeTip({ active, payload }: TooltipProps<number, string>) {
  if (!active || !payload?.length) return null;
  const r = payload[0].payload as Row;
  const hot = r.p >= THRESHOLD;
  return (
    <div className="rounded-xl border border-white/10 bg-[#14171c]/95 px-3 py-2.5 text-xs shadow-[0_16px_40px_-12px_rgba(0,0,0,0.8)] backdrop-blur-md">
      <div className="font-semibold text-text">{dayHourLabel(r.target_ts)}</div>
      <div className="tabular mt-1.5 flex items-baseline gap-1.5">
        <span className="text-lg font-semibold tracking-tight" style={{ color: hot ? RED : "#eceef1" }}>
          {r.p.toFixed(0)}%
        </span>
        <span className="text-muted">chance of a price spike</span>
      </div>
      <div className="mt-1 text-muted">{hot ? "More likely than not: avoid big loads." : "Below the 50% line."}</div>
      <div className="mt-1.5 font-medium text-accent">Click for the breakdown</div>
    </div>
  );
}

function ThresholdLabel({ viewBox }: { viewBox?: { x: number; y: number; width: number } }) {
  if (!viewBox) return null;
  const x = viewBox.x + viewBox.width;
  const y = viewBox.y;
  const w = 64;
  return (
    <g>
      <rect x={x - w} y={y - 9} width={w} height={18} rx={9} fill="#14171c" stroke="rgba(255,255,255,0.12)" />
      <text x={x - w / 2} y={y + 3.5} textAnchor="middle" fontSize={10} fontWeight={600} fill="#aab0ba">
        50% line
      </text>
    </g>
  );
}

function PeakDot({ cx, cy }: { cx?: number; cy?: number }) {
  if (cx == null || cy == null) return <g />;
  return (
    <g>
      <circle cx={cx} cy={cy} r={10} fill={RED} opacity={0.18} />
      <circle cx={cx} cy={cy} r={4.5} fill={RED} stroke="#fff" strokeWidth={1.5} />
    </g>
  );
}

export default function SpikeChart({ hours, onSelect }: { hours: ForecastHour[]; onSelect: (ts: string) => void }) {
  const rows: Row[] = hours.map((h) => ({ target_ts: h.target_ts, p: Math.round((h.spike_prob ?? 0) * 1000) / 10 }));
  const ticks = rows.filter((r) => localHour(r.target_ts) % 6 === 0).map((r) => r.target_ts);
  const max = hours.reduce((m, h) => ((h.spike_prob ?? 0) > (m.spike_prob ?? 0) ? h : m), hours[0]);
  const maxRow = rows.find((r) => r.target_ts === max?.target_ts);
  const above = rows.filter((r) => r.p >= THRESHOLD).length;

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
        <p className="max-w-md text-sm leading-relaxed text-muted">
          Chance each hour that wholesale prices jump above <span className="font-medium text-text">$100/MWh</span>. Click
          the curve to explain an hour.
        </p>
        <dl className="flex gap-6">
          <div>
            <dt className="text-[11px] font-medium uppercase tracking-[0.12em] text-[#8b929e]">Highest</dt>
            <dd className="mt-1 flex items-baseline gap-1.5">
              <AnimatedNumber
                value={(max?.spike_prob ?? 0) * 100}
                format={(n) => `${n.toFixed(0)}%`}
                className="text-2xl font-semibold tracking-tight text-text"
              />
              <span className="text-xs text-muted">{max ? dayHourLabel(max.target_ts) : "–"}</span>
            </dd>
          </div>
          <div>
            <dt className="text-[11px] font-medium uppercase tracking-[0.12em] text-[#8b929e]">Hours over 50%</dt>
            <dd className="mt-1 flex items-baseline gap-1.5">
              <AnimatedNumber value={above} className="text-2xl font-semibold tracking-tight text-text" />
              <span className="text-xs text-muted">of {rows.length}</span>
            </dd>
          </div>
        </dl>
      </div>

      <motion.div
        initial={{ clipPath: "inset(0 100% 0 0)" }}
        whileInView={{ clipPath: "inset(0 0% 0 0)" }}
        viewport={{ once: true, amount: 0 }}
        transition={{ duration: 1, ease: EASE_OUT, delay: 0.1 }}
        className="h-48 w-full cursor-pointer sm:h-56"
        role="img"
        aria-label={`Spike risk by hour. Highest ${pct(max?.spike_prob)} at ${max ? dayHourLabel(max.target_ts) : "unknown"}; ${above} hours above 50%.`}
      >
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart
            data={rows}
            margin={{ top: 16, right: 4, bottom: 0, left: 0 }}
            onClick={(e: unknown) => {
              const ts = (e as { activeLabel?: string })?.activeLabel;
              if (ts) onSelect(ts);
            }}
          >
            <defs>
              <linearGradient id="spikeFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={RED} stopOpacity={0.42} />
                <stop offset="60%" stopColor={RED} stopOpacity={0.1} />
                <stop offset="100%" stopColor={RED} stopOpacity={0} />
              </linearGradient>
              <linearGradient id="spikeStroke" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor="#fb7185" />
                <stop offset="100%" stopColor={RED} />
              </linearGradient>
            </defs>
            <XAxis dataKey="target_ts" ticks={ticks} tickFormatter={hourLabel} tickMargin={8} {...axisProps} />
            <YAxis
              domain={[0, 100]}
              ticks={[0, 25, 50, 75, 100]}
              tickFormatter={(v: number) => `${v}%`}
              width={40}
              {...axisProps}
            />
            <ReferenceLine y={25} stroke="rgba(255,255,255,0.04)" />
            <ReferenceLine y={75} stroke="rgba(255,255,255,0.04)" />
            <ReferenceLine y={THRESHOLD} stroke="rgba(255,255,255,0.22)" strokeDasharray="3 4" label={<ThresholdLabel />} />
            <Tooltip
              content={<SpikeTip />}
              cursor={{ stroke: "rgba(255,255,255,0.25)", strokeDasharray: "3 3" }}
              isAnimationActive={false}
            />
            <Area
              type="monotone"
              dataKey="p"
              stroke="url(#spikeStroke)"
              strokeWidth={2}
              fill="url(#spikeFill)"
              activeDot={{ r: 4, fill: RED, stroke: "#fff", strokeWidth: 1.5 }}
              isAnimationActive={false}
            />
            {maxRow && <ReferenceDot x={maxRow.target_ts} y={maxRow.p} shape={<PeakDot />} />}
          </AreaChart>
        </ResponsiveContainer>
      </motion.div>
    </div>
  );
}
