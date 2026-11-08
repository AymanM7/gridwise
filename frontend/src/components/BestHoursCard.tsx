"use client";

import type { ReactNode } from "react";
import type { Forecast, ForecastHour, Level } from "../lib/types";
import { LEVEL_COLOR, dayHourLabel, hourLabel, pct } from "../lib/format";
import { Stagger, StaggerItem } from "./motion";
import { Empty } from "./ui";
import { Chip, Eyebrow } from "./insights/shared";

function range(start: string, end: string): string {
  return `${dayHourLabel(start)} – ${hourLabel(end)}`;
}

function hoursIn(hours: ForecastHour[], start: string, end: string): ForecastHour[] {
  const a = new Date(start).getTime();
  const b = new Date(end).getTime();
  return hours.filter((h) => {
    const t = new Date(h.target_ts).getTime();
    return t >= a && t <= b;
  });
}

/** Tiny per-hour strain bars for a window (height = strain, color = level). */
function StrainSpark({ hours }: { hours: ForecastHour[] }) {
  if (!hours.length) return null;
  const shown = hours.slice(0, 12);
  return (
    <span aria-hidden className="flex h-5 items-end gap-[2px]">
      {shown.map((h) => (
        <span
          key={h.target_ts}
          className="w-[3px] rounded-[1px]"
          style={{
            height: `${Math.max(18, Math.min(100, h.strain_index))}%`,
            background: LEVEL_COLOR[h.level],
            opacity: 0.85,
          }}
        />
      ))}
    </span>
  );
}

function WindowRow({
  level,
  label,
  hours,
  chip,
}: {
  level: Level;
  label: string;
  hours: ForecastHour[];
  chip: ReactNode;
}) {
  return (
    <div className="group relative flex items-center gap-3 overflow-hidden rounded-xl border border-line bg-panel-2/50 py-2.5 pl-4 pr-3 transition-[transform,border-color,background-color] duration-200 ease-out hover:-translate-y-px hover:border-line-strong hover:bg-panel-2 motion-reduce:hover:translate-y-0">
      <span aria-hidden className="absolute inset-y-2 left-0 w-[2px] rounded-full" style={{ background: LEVEL_COLOR[level] }} />
      <span className="tabular min-w-0 flex-1 truncate text-sm font-medium text-text">{label}</span>
      <StrainSpark hours={hours} />
      {chip}
    </div>
  );
}

function Column({
  level,
  title,
  count,
  children,
}: {
  level: Level;
  title: string;
  count: number;
  children: ReactNode;
}) {
  return (
    <div className="min-w-0">
      <div className="mb-3 flex items-center justify-between">
        <Eyebrow className="flex items-center gap-2">
          <span aria-hidden className="h-1.5 w-1.5 rounded-full" style={{ background: LEVEL_COLOR[level] }} />
          {title}
        </Eyebrow>
        <span className="tabular text-[11px] text-muted">
          {count} window{count === 1 ? "" : "s"}
        </span>
      </div>
      {children}
    </div>
  );
}

export default function BestHoursCard({ forecast }: { forecast: Forecast }) {
  const { best_windows, avoid_windows } = forecast.summary;
  const hours = forecast.hours;
  return (
    <div className="grid gap-6 md:grid-cols-2 md:gap-8">
      <Column level="green" title="Best windows" count={best_windows.length}>
        {best_windows.length ? (
          <Stagger as="ul" className="space-y-2" stagger={0.06}>
            {best_windows.map((w) => (
              <StaggerItem as="li" key={w.start_local}>
                <WindowRow
                  level="green"
                  label={range(w.start_local, w.end_local)}
                  hours={hoursIn(hours, w.start_local, w.end_local)}
                  chip={
                    <Chip title="Average strain index (0–100)">
                      strain <span className="text-text">{Math.round(w.avg_strain)}</span>
                    </Chip>
                  }
                />
              </StaggerItem>
            ))}
          </Stagger>
        ) : (
          <Empty>No clearly green windows in the next 48 hours.</Empty>
        )}
      </Column>
      <Column level="red" title="Avoid big loads" count={avoid_windows.length}>
        {avoid_windows.length ? (
          <Stagger as="ul" className="space-y-2" stagger={0.06} delay={0.08}>
            {avoid_windows.map((w) => (
              <StaggerItem as="li" key={w.start_local}>
                <WindowRow
                  level="red"
                  label={range(w.start_local, w.end_local)}
                  hours={hoursIn(hours, w.start_local, w.end_local)}
                  chip={
                    <Chip title="Highest chance of a price spike in this window">
                      spike <span className="text-text">{pct(w.max_spike_prob)}</span>
                    </Chip>
                  }
                />
              </StaggerItem>
            ))}
          </Stagger>
        ) : (
          <Empty>Nothing to avoid. The grid looks comfortable.</Empty>
        )}
      </Column>
    </div>
  );
}
