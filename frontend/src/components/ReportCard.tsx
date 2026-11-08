"use client";

import { Crosshair, Gauge, Target, Zap } from "lucide-react";
import type { ReportCard as RC, ReportRow } from "../lib/types";
import { LEVEL_COLOR, shortDay } from "../lib/format";
import { EASE_OUT, motion } from "./motion";
import { Empty } from "./ui";
import { ACCENT, Chip, Eyebrow, StatTile } from "./insights/shared";

function n(v: number | null | undefined, d = 1, suffix = "") {
  return v == null ? "–" : `${v.toFixed(d)}${suffix}`;
}

type Grade = "good" | "ok" | "poor";
/** Net-load MAPE grade: ≤10% good, ≤20% ok, above that poor. */
function grade(mape: number | null | undefined): Grade | null {
  if (mape == null) return null;
  return mape <= 10 ? "good" : mape <= 20 ? "ok" : "poor";
}
const GRADE_COLOR: Record<Grade, string> = { good: LEVEL_COLOR.green, ok: LEVEL_COLOR.yellow, poor: LEVEL_COLOR.red };

function ErrorChip({ mape }: { mape: number | null }) {
  const g = grade(mape);
  if (!g) return <span className="text-muted">–</span>;
  return (
    <span className="tabular inline-flex items-center gap-1.5 rounded-md border border-line bg-panel-2 px-1.5 py-0.5 text-xs font-medium text-text">
      <span aria-hidden className="h-1.5 w-1.5 rounded-full" style={{ background: GRADE_COLOR[g] }} />
      {n(mape, 1, "%")}
      <span className="text-[10px] font-normal text-muted">{g}</span>
    </span>
  );
}

/** Linear meter for band coverage with a tick at the 80% target. */
function BandMeter({ value }: { value: number | null }) {
  const v = value == null ? 0 : Math.max(0, Math.min(100, value));
  const onTarget = value != null && value >= 75;
  return (
    <div className="mt-3" aria-hidden>
      <div className="relative h-1.5 rounded-full bg-panel-3">
        <div
          className="h-full rounded-full transition-[width] duration-700 ease-out"
          style={{ width: `${v}%`, background: onTarget ? ACCENT : MUTED_FILL }}
        />
        <span className="absolute -top-1 h-3.5 w-px bg-text/70" style={{ left: "80%" }} />
      </div>
    </div>
  );
}
const MUTED_FILL = "#8b929e";

/** Sparkline of daily net-load error (oldest → newest). */
function ErrorSpark({ rows }: { rows: ReportRow[] }) {
  const pts = [...rows].reverse().filter((r) => r.mape != null);
  if (pts.length < 2) return null;
  const W = 96;
  const H = 24;
  const max = Math.max(...pts.map((r) => r.mape!), 1);
  const xy = pts.map((r, i) => [(i / (pts.length - 1)) * (W - 4) + 2, H - 3 - (r.mape! / max) * (H - 6)] as const);
  const d = xy.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const last = xy[xy.length - 1];
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Daily net-load error trend, oldest to newest">
      <path d={d} fill="none" stroke={ACCENT} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={last[0]} cy={last[1]} r={2.5} fill={ACCENT} />
    </svg>
  );
}

export default function ReportCard({ rc }: { rc: RC }) {
  const l = rc.latest;
  if (!l) return <Empty>No graded days yet. The report card fills in once yesterday&apos;s actuals arrive.</Empty>;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2 text-sm text-muted">
        How did we do on <span className="font-medium text-text">{shortDay(l.date)}</span>?
        <Chip className={l.source === "live" ? "border-sky-300/30 text-sky-100" : ""}>
          {l.source === "live" && <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-accent" />}
          {l.source === "live" ? "Live forecast" : "Backtest"}
        </Chip>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <StatTile
          icon={<Gauge />}
          label="Net-load error"
          value={l.mape}
          format={(v) => `${v.toFixed(1)}%`}
          sub="MAPE, lower is better"
        />
        <StatTile
          icon={<Zap />}
          label="Demand error"
          value={l.demand_mape}
          format={(v) => `${v.toFixed(1)}%`}
          sub="MAPE"
        />
        <StatTile
          icon={<Crosshair />}
          label="Spikes caught"
          display={l.spike_hours_actual ? undefined : "none"}
          value={l.spike_hours_actual ? l.spike_hours_caught : null}
          format={(v) => `${Math.round(v)} of ${l.spike_hours_actual}`}
          sub={l.spike_hours_actual ? "price-spike hours" : "no spikes that day"}
        />
        <StatTile
          icon={<Target />}
          label="Inside band"
          value={l.band_coverage}
          format={(v) => `${Math.round(v)}%`}
          sub={
            <span className="flex items-center gap-1.5">
              <span aria-hidden className="h-2.5 w-px bg-text/70" />
              target ≈ 80% of hours
            </span>
          }
        >
          <BandMeter value={l.band_coverage} />
        </StatTile>
      </div>

      {rc.rows.length > 1 && (
        <div>
          <div className="mb-2 flex items-center justify-between gap-3">
            <Eyebrow>Last {rc.rows.length} days</Eyebrow>
            <span className="flex items-center gap-2 text-[11px] text-muted">
              error trend
              <ErrorSpark rows={rc.rows} />
            </span>
          </div>
          <table className="w-full table-fixed text-left text-xs">
            <thead>
              <tr className="text-[11px] uppercase tracking-[0.1em] text-muted">
                <th scope="col" className="w-[30%] py-2 pl-2 font-medium">Day</th>
                <th scope="col" className="w-[30%] py-2 font-medium sm:w-[26%]">Error</th>
                <th scope="col" className="hidden py-2 font-medium sm:table-cell">Demand</th>
                <th scope="col" className="py-2 font-medium">Spikes</th>
                <th scope="col" className="py-2 pr-2 text-right font-medium">In band</th>
              </tr>
            </thead>
            <motion.tbody
              className="tabular"
              initial="hidden"
              whileInView="show"
              viewport={{ once: true, amount: 0 }}
              variants={{ hidden: {}, show: { transition: { staggerChildren: 0.04 } } }}
            >
              {rc.rows.map((r) => (
                <motion.tr
                  key={`${r.date}-${r.source}`}
                  className="group"
                  variants={{
                    hidden: { opacity: 0 },
                    show: { opacity: 1, transition: { duration: 0.45, ease: EASE_OUT } },
                  }}
                >
                  <td className="rounded-l-lg py-2 pl-2 text-text transition-colors group-odd:bg-white/[0.02] group-hover:bg-white/[0.04]">
                    <span className="flex items-center gap-1.5">
                      {shortDay(r.date).replace(/^\w+, /, "")}
                      {r.source === "live" && (
                        <span className="h-1.5 w-1.5 rounded-full bg-accent" title="Live forecast">
                          <span className="sr-only">(live)</span>
                        </span>
                      )}
                    </span>
                  </td>
                  <td className="py-1.5 transition-colors group-odd:bg-white/[0.02] group-hover:bg-white/[0.04]">
                    <ErrorChip mape={r.mape} />
                  </td>
                  <td className="hidden py-2 text-muted transition-colors group-odd:bg-white/[0.02] group-hover:bg-white/[0.04] sm:table-cell">
                    {n(r.demand_mape, 1, "%")}
                  </td>
                  <td className="py-2 text-muted transition-colors group-odd:bg-white/[0.02] group-hover:bg-white/[0.04]">
                    {r.spike_hours_actual ? `${r.spike_hours_caught}/${r.spike_hours_actual}` : "–"}
                  </td>
                  <td className="rounded-r-lg py-2 pr-2 text-right text-muted transition-colors group-odd:bg-white/[0.02] group-hover:bg-white/[0.04]">
                    {n(r.band_coverage, 0, "%")}
                  </td>
                </motion.tr>
              ))}
            </motion.tbody>
          </table>
          <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted">
            <span>Error grade:</span>
            {(["good", "ok", "poor"] as Grade[]).map((g) => (
              <span key={g} className="inline-flex items-center gap-1">
                <span aria-hidden className="h-1.5 w-1.5 rounded-full" style={{ background: GRADE_COLOR[g] }} />
                {g} {g === "good" ? "≤10%" : g === "ok" ? "≤20%" : ">20%"}
              </span>
            ))}
          </p>
        </div>
      )}
      {rc.note && <p className="text-xs leading-relaxed text-muted">{rc.note}</p>}
    </div>
  );
}
