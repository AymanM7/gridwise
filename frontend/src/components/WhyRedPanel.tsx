"use client";

import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowDownRight,
  ArrowUpRight,
  CalendarDays,
  MousePointerClick,
  Quote,
  Snowflake,
  Sun,
  Thermometer,
  TrendingUp,
  TriangleExclamationPoint,
  Wind,
  X,
  type LucideIcon,
} from "lucide-react";
import { fetchDrivers } from "../lib/api";
import { plainDriver } from "../lib/drivers";
import type { Driver, ForecastHour } from "../lib/types";
import { LEVEL_COLOR, dayHourLabel, gw, pct } from "../lib/format";
import { AnimatePresence, AnimatedNumber, EASE_OUT, motion } from "./motion";
import { Empty, ErrorBox, LevelPill, Loading } from "./ui";

const UP = "#f43f5e";
const DOWN = "#34d399";

function iconFor(d: Driver, raises: boolean): LucideIcon {
  switch (d.feature) {
    case "ercot_wind_forecast":
      return Wind;
    case "ercot_solar_forecast":
      return Sun;
    case "recent_demand_level":
      return TrendingUp;
    case "cdd":
      return Thermometer;
    case "hdd":
      return Snowflake;
    case "demand_lag_48h":
      return CalendarDays;
    default:
      return raises ? ArrowUpRight : ArrowDownRight;
  }
}

function Label({ children }: { children: ReactNode }) {
  return <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-[#8b929e]">{children}</div>;
}

export default function WhyRedPanel({
  hour,
  whyRedFallback,
  onClose,
}: {
  hour: ForecastHour | null;
  whyRedFallback?: string;
  onClose: () => void;
}) {
  return (
    <div aria-live="polite">
      <AnimatePresence mode="wait" initial={false}>
        {hour ? (
          <motion.div
            key={hour.target_ts}
            initial={{ opacity: 0, y: 8, filter: "blur(4px)" }}
            animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
            exit={{ opacity: 0, y: -6, filter: "blur(4px)" }}
            transition={{ duration: 0.28, ease: EASE_OUT }}
          >
            <HourDetail hour={hour} whyRedFallback={whyRedFallback} onClose={onClose} />
          </motion.div>
        ) : (
          <motion.div key="empty" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }}>
            <EmptyHint />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function EmptyHint() {
  const bars = [38, 52, 46, 64, 80, 92, 74, 58, 44, 36, 50, 62];
  const col = (h: number) => (h > 85 ? LEVEL_COLOR.red : h >= 60 ? LEVEL_COLOR.yellow : LEVEL_COLOR.green);
  return (
    <div className="rounded-xl border border-dashed border-line-strong bg-white/[0.01] px-5 py-8 text-center">
      <div className="relative mx-auto flex h-16 w-44 items-end justify-center gap-1" aria-hidden>
        {bars.map((h, i) => (
          <span
            key={i}
            className="w-2.5 rounded-t-[3px]"
            style={{ height: `${h}%`, background: `linear-gradient(180deg, ${col(h)}, ${col(h)}22)`, opacity: i === 5 ? 1 : 0.35 }}
          />
        ))}
        <MousePointerClick className="absolute -top-4 left-[50%] h-5 w-5 text-text" />
      </div>
      <p className="mt-5 text-sm font-medium text-text">Tap any hour on the timeline</p>
      <p className="mt-1 text-xs text-muted">See why it is green, yellow or red, and what is driving it.</p>
    </div>
  );
}

function HourDetail({
  hour,
  whyRedFallback,
  onClose,
}: {
  hour: ForecastHour;
  whyRedFallback?: string;
  onClose: () => void;
}) {
  const q = useQuery({
    queryKey: ["drivers", hour.target_ts],
    queryFn: () => fetchDrivers(hour.target_ts),
    staleTime: 30 * 60_000,
  });

  const d = q.data?.data;
  const sentence = d?.why_red ?? whyRedFallback ?? null;
  const width = hour.band_low_mw != null && hour.band_high_mw != null ? hour.band_high_mw - hour.band_low_mw : null;
  const rel = width != null && hour.net_load_mw ? width / hour.net_load_mw : null;
  const confidence = hour.low_confidence ? "low" : rel != null && rel < 0.25 ? "high" : "medium";
  const segs = confidence === "high" ? 3 : confidence === "medium" ? 2 : 1;
  const title = hour.level === "red" ? "Why red?" : hour.level === "yellow" ? "Why yellow?" : "Why green?";
  const c = LEVEL_COLOR[hour.level];
  const maxAbs = d?.drivers.length ? Math.max(...d.drivers.map((x) => Math.abs(x.mw ?? 0)), 1) : 1;

  return (
    <div className="space-y-5">
      {/* level-colored header */}
      <div
        className="relative overflow-hidden rounded-xl border p-4"
        style={{ borderColor: `${c}33`, background: `linear-gradient(160deg, ${c}1f 0%, ${c}08 45%, transparent 100%)` }}
      >
        <div aria-hidden className="absolute inset-x-0 top-0 h-px" style={{ background: `linear-gradient(90deg, ${c}, transparent)` }} />
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-[11px] font-semibold uppercase tracking-[0.14em]" style={{ color: c }}>
              {title}
            </div>
            <div className="mt-1 text-xl font-semibold tracking-tight text-text">{dayHourLabel(hour.target_ts)}</div>
          </div>
          <div className="flex items-center gap-2">
            <LevelPill level={hour.level} />
            <button
              onClick={onClose}
              className="grid h-7 w-7 place-items-center rounded-lg text-muted transition-colors hover:bg-white/[0.06] hover:text-text"
              aria-label="Close explanation"
            >
              <X className="h-4 w-4" aria-hidden />
            </button>
          </div>
        </div>
        <dl className="tabular mt-4 grid grid-cols-3 divide-x divide-white/[0.08]">
          {[
            { k: "Strain", v: <AnimatedNumber value={hour.strain_index} />, u: "/100" },
            { k: "Net load", v: <AnimatedNumber value={(hour.net_load_mw ?? 0) / 1000} format={(n) => n.toFixed(1)} />, u: "GW" },
            { k: "Spike risk", v: <AnimatedNumber value={(hour.spike_prob ?? 0) * 100} format={(n) => n.toFixed(0)} />, u: "%" },
          ].map((m, i) => (
            <div key={m.k} className={i === 0 ? "pr-3" : "px-3"}>
              <dt className="text-[11px] text-muted">{m.k}</dt>
              <dd className="mt-0.5 text-lg font-semibold tracking-tight text-text">
                {m.v}
                <span className="ml-0.5 text-xs font-normal text-muted">{m.u}</span>
              </dd>
            </div>
          ))}
        </dl>
      </div>

      {/* drivers */}
      <div>
        <div className="mb-3 flex items-center justify-between gap-2">
          <Label>Top drivers</Label>
          <div className="flex items-center gap-3 text-[11px] text-muted">
            <span className="inline-flex items-center gap-1">
              <span className="h-1.5 w-3 rounded-full" style={{ background: UP }} aria-hidden /> raises
            </span>
            <span className="inline-flex items-center gap-1">
              <span className="h-1.5 w-3 rounded-full" style={{ background: DOWN }} aria-hidden /> eases
            </span>
          </div>
        </div>
        {q.isPending ? (
          <Loading label="Loading drivers" className="h-32" />
        ) : q.isError ? (
          <ErrorBox message={`Couldn't load drivers: ${(q.error as Error).message}`} onRetry={() => q.refetch()} />
        ) : !d || !d.drivers.length ? (
          <Empty>
            {q.data?.source === "fixtures"
              ? "The demo snapshot includes drivers for 3 hours (the reddest, the riskiest and the calmest). Try one of those, or run against the live API."
              : "No driver breakdown for this hour yet."}
          </Empty>
        ) : (
          <ol className="space-y-1.5">
            {d.drivers.map((dr, idx) => {
              const p = plainDriver(dr);
              const Icon = iconFor(dr, p.raises);
              const col = p.raises ? UP : DOWN;
              const w = (Math.abs(dr.mw ?? 0) / maxAbs) * 50;
              return (
                <motion.li
                  key={dr.rank}
                  initial={{ opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.4, ease: EASE_OUT, delay: 0.05 + idx * 0.06 }}
                  className="rounded-xl border border-line bg-white/[0.02] p-3 transition-colors hover:border-line-strong"
                >
                  <div className="flex items-start gap-3">
                    <span className="tabular mt-1 w-3 shrink-0 font-mono text-[11px] text-[#7d838e]">{dr.rank}</span>
                    <span
                      aria-hidden
                      className="grid h-7 w-7 shrink-0 place-items-center rounded-lg border"
                      style={{ color: col, borderColor: `${col}33`, background: `${col}12` }}
                    >
                      <Icon className="h-3.5 w-3.5" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="text-[13px] leading-snug text-text">{p.text}</div>
                      <div className="mt-2 flex items-center gap-2.5">
                        <div className="relative h-1.5 flex-1 rounded-full bg-white/[0.05]" aria-hidden>
                          <span className="absolute inset-y-[-3px] left-1/2 w-px bg-white/20" />
                          <motion.span
                            className="absolute inset-y-0 rounded-full"
                            style={{
                              background: p.raises ? `linear-gradient(90deg, ${col}55, ${col})` : `linear-gradient(270deg, ${col}55, ${col})`,
                              ...(p.raises ? { left: "50%" } : { right: "50%" }),
                            }}
                            initial={{ width: 0 }}
                            animate={{ width: `${w}%` }}
                            transition={{ duration: 0.7, ease: EASE_OUT, delay: 0.15 + idx * 0.06 }}
                          />
                        </div>
                        <span className="tabular w-[4.5rem] shrink-0 text-right text-xs font-medium" style={{ color: col }}>
                          {p.impact.replace(" net load", "")}
                        </span>
                      </div>
                    </div>
                  </div>
                </motion.li>
              );
            })}
          </ol>
        )}
      </div>

      {/* plain-language sentence */}
      {sentence && (
        <figure className="relative rounded-xl border border-line bg-white/[0.02] py-3.5 pl-10 pr-4">
          <Quote className="absolute left-3.5 top-4 h-4 w-4 text-[#7d838e]" aria-hidden />
          <blockquote className="text-[13px] leading-relaxed text-text/90">{sentence}</blockquote>
        </figure>
      )}

      {/* confidence */}
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="flex items-center gap-3">
          <Label>Confidence</Label>
          <div className="flex gap-1" role="meter" aria-label={`Confidence ${confidence}`} aria-valuemin={1} aria-valuemax={3} aria-valuenow={segs}>
            {[1, 2, 3].map((i) => (
              <motion.span
                key={i}
                className="h-1.5 w-5 rounded-full"
                initial={{ opacity: 0.3 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.2 + i * 0.08 }}
                style={{ background: i <= segs ? (segs === 1 ? LEVEL_COLOR.yellow : "var(--accent)") : "rgba(255,255,255,0.08)" }}
              />
            ))}
          </div>
          <span className="text-xs font-medium capitalize text-text">{confidence}</span>
        </div>
        {width != null && <span className="tabular text-xs text-muted">Range {gw(width)} wide</span>}
      </div>
      {hour.low_confidence && (
        <div className="-mt-2 flex items-center gap-1.5 text-xs text-amber-200">
          <TriangleExclamationPoint className="h-3.5 w-3.5" aria-hidden />
          Uncertain: weather forecast is shifting
        </div>
      )}
      <span className="sr-only">Spike risk {pct(hour.spike_prob)}</span>
    </div>
  );
}
