"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchDrivers } from "../lib/api";
import { plainDriver } from "../lib/drivers";
import type { ForecastHour } from "../lib/types";
import { LEVEL_COLOR, dayHourLabel, gw, pct } from "../lib/format";
import { Empty, ErrorBox, LevelPill, Loading } from "./ui";

export default function WhyRedPanel({
  hour,
  whyRedFallback,
  onClose,
}: {
  hour: ForecastHour | null;
  whyRedFallback?: string;
  onClose: () => void;
}) {
  const q = useQuery({
    queryKey: ["drivers", hour?.target_ts],
    queryFn: () => fetchDrivers(hour!.target_ts),
    enabled: !!hour,
    staleTime: 30 * 60_000,
  });

  if (!hour) {
    return <Empty>Tap any hour on the timeline to see why it is green, yellow or red.</Empty>;
  }
  const d = q.data?.data;
  const sentence = d?.why_red ?? whyRedFallback ?? null;
  const width = hour.band_low_mw != null && hour.band_high_mw != null ? hour.band_high_mw - hour.band_low_mw : null;
  const rel = width != null && hour.net_load_mw ? width / hour.net_load_mw : null;
  const confidence = hour.low_confidence ? "low" : rel != null && rel < 0.25 ? "high" : "medium";
  const title = hour.level === "red" ? "Why red?" : hour.level === "yellow" ? "Why yellow?" : "Why green?";

  return (
    <div className="rounded-xl border p-4" style={{ borderColor: `${LEVEL_COLOR[hour.level]}55`, background: `${LEVEL_COLOR[hour.level]}0d` }} aria-live="polite">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-lg font-semibold">
            {title} {dayHourLabel(hour.target_ts)}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted">
            <LevelPill level={hour.level} />
            <span className="tabular">strain {Math.round(hour.strain_index)}</span>·<span className="tabular">net load {gw(hour.net_load_mw)}</span>·
            <span className="tabular">spike risk {pct(hour.spike_prob)}</span>
          </div>
        </div>
        <button onClick={onClose} className="rounded-lg px-2 py-1 text-muted hover:bg-panel-2 hover:text-text" aria-label="Close explanation">
          ✕
        </button>
      </div>

      <div className="mt-3">
        {q.isLoading ? (
          <Loading label="Loading drivers" className="h-24" />
        ) : q.isError ? (
          <ErrorBox message={`Couldn't load drivers: ${(q.error as Error).message}`} onRetry={() => q.refetch()} />
        ) : !d || !d.drivers.length ? (
          <Empty>
            {q.data?.source === "fixtures"
              ? "The demo snapshot includes drivers for 3 hours (the reddest, the riskiest and the calmest). Try one of those, or run against the live API."
              : "No driver breakdown for this hour yet."}
          </Empty>
        ) : (
          <ol className="space-y-2">
            {d.drivers.map((dr) => {
              const p = plainDriver(dr);
              return (
                <li key={dr.rank} className="flex items-start gap-3 rounded-lg bg-panel-2 px-3 py-2">
                  <span className="tabular w-4 text-sm text-muted">{dr.rank}.</span>
                  <span aria-hidden>{p.icon}</span>
                  <div className="flex-1 text-sm">
                    <div>{p.text}</div>
                    <div className={`tabular text-xs ${p.raises ? "text-red-300" : "text-green-300"}`}>{p.impact}</div>
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </div>

      {sentence && <p className="mt-3 text-sm italic text-text/90">“{sentence}”</p>}
      <p className="mt-2 text-xs text-muted">
        Confidence: <b className="text-text">{confidence}</b>
        {width != null && <> (band {gw(width)} wide)</>}
        {hour.low_confidence && " · ⚠️ Uncertain: weather forecast is shifting"}
      </p>
    </div>
  );
}
