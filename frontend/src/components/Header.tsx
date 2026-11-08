"use client";

import type { ReactNode } from "react";
import { Clock3, CloudOff, Info, TrendingUp, Zap } from "lucide-react";
import type { Forecast, Health, Level } from "../lib/types";
import type { Source } from "../lib/api";
import { LEVEL_COLOR, LEVEL_TEXT, ageLabel, ageMinutes, dayHourLabel, longDay, timestampLabel, tomorrowLocal } from "../lib/format";
import { Skeleton } from "./ui";
import { AnimatedNumber, EASE_OUT, PulseDot, motion } from "./motion";
import StrainGauge from "./hero/StrainGauge";
import Notice from "./hero/Notice";
import { PowerLines } from "./shader/Backgrounds";

const STALE_MIN = 120;
const LEVELS: Level[] = ["green", "yellow", "red"];

function overall(f: Forecast): Level {
  const c = f.summary.level_counts;
  return c.red > 0 ? "red" : c.yellow > 0 ? "yellow" : "green";
}

/** "Tight grid ahead: 18 red hours. Strain peaks…" -> { tag, lead, rest } */
function splitVerdict(v: string) {
  const dot = v.indexOf(". ");
  const lead = dot > 0 ? v.slice(0, dot + 1) : v;
  const rest = dot > 0 ? v.slice(dot + 2) : "";
  const colon = lead.indexOf(":");
  return colon > 0 && colon < 40
    ? { tag: lead.slice(0, colon + 1), lead: lead.slice(colon + 1).trim(), rest }
    : { tag: "", lead, rest };
}

function Chip({
  label,
  children,
  sub,
  delay,
  className = "",
}: {
  label: string;
  children: ReactNode;
  sub?: ReactNode;
  delay: number;
  className?: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: EASE_OUT, delay }}
      className={`group min-w-0 rounded-xl border border-line bg-white/[0.02] px-4 py-3 transition-[border-color,transform] duration-200 hover:-translate-y-px hover:border-line-strong ${className}`}
    >
      <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-[#8b929e]">{label}</div>
      <div className="mt-1.5">{children}</div>
      {sub && <div className="tabular mt-1 text-xs text-muted">{sub}</div>}
    </motion.div>
  );
}

export default function Header({
  forecast,
  health,
  source,
  loading,
}: {
  forecast?: Forecast;
  health?: Health;
  source?: Source;
  loading: boolean;
}) {
  const runTs = forecast?.run_ts ?? health?.forecast_run_ts ?? null;
  const age = source === "api" && health?.forecast_age_minutes != null ? health.forecast_age_minutes : ageMinutes(runTs);
  const stale = source === "api" && age != null && age > STALE_MIN;
  const lvl = forecast ? overall(forecast) : null;

  const status =
    source === "fixtures"
      ? { label: "Demo", color: "var(--accent)" }
      : source === "snapshot"
        ? { label: "Offline", color: "var(--yellow)" }
        : stale
          ? { label: "Delayed", color: "var(--yellow)" }
          : { label: "Live", color: "var(--green)" };

  return (
    <header className="space-y-3">
      {source === "fixtures" && (
        <Notice icon={<Info />}>
          <span className="text-text">Demo mode.</span> Showing a saved snapshot of real GridWise output
          {runTs ? ` from ${timestampLabel(runTs)}` : ""}.
        </Notice>
      )}
      {source === "snapshot" && (
        <Notice tone="warn" icon={<CloudOff />} alert>
          <span className="text-text">The live forecast service is unreachable.</span> Showing the last saved forecast
          {runTs ? ` (${timestampLabel(runTs)})` : ""}; it may be outdated.
        </Notice>
      )}
      {stale && (
        <Notice tone="warn" icon={<Clock3 />} alert>
          <span className="text-text">Forecast last updated {ageLabel(age)}</span> (data through {runTs ? timestampLabel(runTs) : "unknown"}).
          The hourly pipeline may be delayed.
        </Notice>
      )}

      {loading && !forecast ? (
        <Skeleton className="h-[340px] rounded-[24px]" />
      ) : forecast && lvl ? (
        <Hero forecast={forecast} lvl={lvl} runTs={runTs} age={age} status={status} />
      ) : (
        <section className="surface p-6 sm:p-8">
          <h1 className="text-2xl font-semibold tracking-tight">GridWise</h1>
          <p className="mt-1 text-sm text-muted">Texas grid forecast. The 48-hour outlook will appear here once it is published.</p>
        </section>
      )}
    </header>
  );
}

function Hero({
  forecast,
  lvl,
  runTs,
  age,
  status,
}: {
  forecast: Forecast;
  lvl: Level;
  runTs: string | null;
  age: number | null;
  status: { label: string; color: string };
}) {
  const s = forecast.summary;
  const c = LEVEL_COLOR[lvl];
  const v = splitVerdict(s.verdict);
  const total = LEVELS.reduce((n, l) => n + s.level_counts[l], 0) || 1;

  return (
    <section
      aria-labelledby="verdict"
      className="surface relative overflow-hidden !rounded-[24px] p-5 sm:p-8 lg:p-10"
    >
      {/* animated power-line shader + level glow + top hairline */}
      <div aria-hidden className="pointer-events-none absolute inset-0 opacity-90">
        <PowerLines tint={c} intensity={lvl === "red" ? 1.15 : 0.9} />
      </div>
      <div
        aria-hidden
        className="pointer-events-none absolute -right-24 -top-48 h-[460px] w-[680px] rounded-full opacity-60 blur-3xl"
        style={{ background: `radial-gradient(closest-side, ${c}2e, transparent)` }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-px"
        style={{ background: `linear-gradient(90deg, transparent, ${c}99 50%, transparent)` }}
      />

      <div className="relative grid items-center gap-8 lg:grid-cols-[1fr_auto] lg:gap-12">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-xs text-muted" aria-live="polite">
            <span className="inline-flex items-center gap-2 rounded-full border border-line-strong bg-white/[0.03] py-1 pl-2.5 pr-3 font-medium text-text">
              <PulseDot color={status.color} />
              {status.label}
            </span>
            {runTs && (
              <span className="tabular">
                Updated <span className="text-text">{ageLabel(age)}</span>
                <span className="mx-1.5 text-faint">/</span>
                Data through {timestampLabel(runTs)}
              </span>
            )}
          </div>

          <div className="mt-6 text-[11px] font-medium uppercase tracking-[0.16em] text-[#8b929e]" suppressHydrationWarning>
            Next 48 hours · Tomorrow is {longDay(tomorrowLocal())}
          </div>
          <motion.h1
            id="verdict"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, ease: EASE_OUT }}
            className="mt-3 max-w-3xl text-[1.85rem] font-semibold leading-[1.1] tracking-[-0.03em] text-balance text-text sm:text-4xl lg:text-[2.75rem]"
          >
            {v.tag && <span className="text-shimmer" style={{ color: c }}>{v.tag} </span>}
            {v.lead}
          </motion.h1>
          {v.rest && (
            <motion.p
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, ease: EASE_OUT, delay: 0.08 }}
              className="tabular mt-3 max-w-2xl text-base text-muted sm:text-lg"
            >
              {v.rest}
            </motion.p>
          )}
        </div>

        <motion.div
          initial={{ opacity: 0, scale: 0.96 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.6, ease: EASE_OUT, delay: 0.1 }}
          className="flex justify-center lg:justify-end"
        >
          <StrainGauge
            value={s.peak.strain_index}
            level={s.peak.level}
            caption={`${LEVEL_TEXT[s.peak.level]} · ${dayHourLabel(s.peak.local_time)}`}
          />
        </motion.div>
      </div>

      <div className="relative mt-8 grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Chip label="Hour mix · 48 h" delay={0.15} className="col-span-2 sm:col-span-1">
          <div className="flex h-1.5 w-full gap-0.5 overflow-hidden rounded-full" aria-hidden>
            {LEVELS.map((l) =>
              s.level_counts[l] ? (
                <motion.span
                  key={l}
                  className="h-full rounded-full"
                  style={{ background: LEVEL_COLOR[l] }}
                  initial={{ width: 0 }}
                  animate={{ width: `${(s.level_counts[l] / total) * 100}%` }}
                  transition={{ duration: 0.8, ease: EASE_OUT, delay: 0.25 }}
                />
              ) : null,
            )}
          </div>
          <div className="mt-2.5 flex items-center gap-3.5 text-sm">
            {LEVELS.map((l) => (
              <span key={l} className="inline-flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full" style={{ background: LEVEL_COLOR[l] }} aria-hidden />
                <AnimatedNumber value={s.level_counts[l]} className="font-semibold text-text" />
                <span className="text-muted">{l}</span>
              </span>
            ))}
          </div>
        </Chip>
        <Chip label="Peak net load" sub={`at ${dayHourLabel(s.peak.local_time)}`} delay={0.2}>
          <div className="flex items-center gap-2">
            <Zap className="h-4 w-4 text-muted" aria-hidden />
            <AnimatedNumber
              value={s.peak.net_load_mw / 1000}
              format={(n) => n.toFixed(1)}
              className="text-2xl font-semibold tracking-tight text-text"
            />
            <span className="text-sm text-muted">GW</span>
          </div>
        </Chip>
        <Chip label="Max spike risk" sub={
            <>
              at {dayHourLabel(s.max_spike.local_time)}
              <span className="hidden sm:inline"> · price above $100/MWh</span>
            </>
          } delay={0.25}>
          <div className="flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-muted" aria-hidden />
            <AnimatedNumber
              value={s.max_spike.spike_prob * 100}
              format={(n) => n.toFixed(0)}
              className="text-2xl font-semibold tracking-tight"
            />
            <span className="text-sm text-muted">%</span>
          </div>
        </Chip>
      </div>
    </section>
  );
}
