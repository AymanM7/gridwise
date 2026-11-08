"use client";

import type { Forecast, Health, Level } from "../lib/types";
import type { Source } from "../lib/api";
import { LEVEL_COLOR, ageLabel, ageMinutes, longDay, timestampLabel, tomorrowLocal } from "../lib/format";
import { Skeleton } from "./ui";

const STALE_MIN = 120;

function overall(f: Forecast): Level {
  const c = f.summary.level_counts;
  return c.red > 0 ? "red" : c.yellow > 0 ? "yellow" : "green";
}

const EMOJI: Record<Level, string> = { green: "🟢", yellow: "🟡", red: "🔴" };

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

  return (
    <header className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <div className="flex items-center gap-2 text-2xl font-bold tracking-tight sm:text-3xl">
            <span aria-hidden className="inline-block h-3 w-3 rounded-full bg-lvl-green shadow-[0_0_12px_#22c55e]" />
            <span>
              Grid<span className="text-lvl-green">Wise</span>
            </span>
          </div>
          <p className="text-sm text-muted" suppressHydrationWarning>Texas grid forecast · Tomorrow is {longDay(tomorrowLocal())}</p>
        </div>
        <div className="text-right text-xs text-muted" aria-live="polite">
          {runTs ? (
            <>
              <div>
                Forecast updated <span className="tabular text-text">{ageLabel(age)}</span>
              </div>
              {/* run_ts is the data anchor hour (ERCOT/EIA lag ~3 h); the age above is time since the pipeline ran */}
              <div className="tabular">Data through {timestampLabel(runTs)}</div>
            </>
          ) : loading ? (
            <span>Checking freshness…</span>
          ) : null}
        </div>
      </div>

      {source === "fixtures" && (
        <div className="rounded-xl border border-sky-400/30 bg-sky-400/10 px-3 py-2 text-sm text-sky-100">
          Demo mode: showing a saved snapshot of real GridWise output{runTs ? ` from ${timestampLabel(runTs)}` : ""}.
        </div>
      )}
      {source === "snapshot" && (
        <div role="alert" className="rounded-xl border border-amber-400/40 bg-amber-400/10 px-3 py-2 text-sm text-amber-100">
          ⚠️ The live forecast service is unreachable. Showing the last saved forecast{runTs ? ` (${timestampLabel(runTs)})` : ""}; it may be
          outdated.
        </div>
      )}
      {stale && (
        <div role="alert" className="rounded-xl border border-amber-400/40 bg-amber-400/10 px-3 py-2 text-sm text-amber-100">
          ⚠️ Forecast last updated {ageLabel(age)} (data through {runTs ? timestampLabel(runTs) : "unknown"}). The hourly pipeline may be delayed.
        </div>
      )}

      {loading && !forecast ? (
        <Skeleton className="h-20" />
      ) : forecast && lvl ? (
        <div
          className="rounded-2xl border p-4 sm:p-5"
          style={{ borderColor: `${LEVEL_COLOR[lvl]}66`, background: `${LEVEL_COLOR[lvl]}14` }}
        >
          <div className="text-xs font-semibold uppercase tracking-wider text-muted">Next 48 hours</div>
          <p className="mt-1 text-lg font-semibold leading-snug sm:text-xl">
            <span aria-hidden>{EMOJI[lvl]} </span>
            {forecast.summary.verdict}
          </p>
          <div className="mt-2 flex flex-wrap gap-3 text-sm text-muted">
            {(["green", "yellow", "red"] as Level[]).map((l) => (
              <span key={l} className="inline-flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-sm" style={{ background: LEVEL_COLOR[l] }} aria-hidden />
                <span className="tabular text-text">{forecast.summary.level_counts[l]}</span> {l} h
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </header>
  );
}
