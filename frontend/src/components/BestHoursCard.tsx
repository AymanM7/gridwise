import type { Forecast } from "../lib/types";
import { dayHourLabel, hourLabel, pct } from "../lib/format";
import { Empty } from "./ui";

function range(start: string, end: string): string {
  return `${dayHourLabel(start)} – ${hourLabel(end)}`;
}

export default function BestHoursCard({ forecast }: { forecast: Forecast }) {
  const { best_windows, avoid_windows } = forecast.summary;
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <div>
        <h3 className="mb-2 text-sm font-semibold text-lvl-green">✅ Best hours to use power</h3>
        {best_windows.length ? (
          <ul className="space-y-2">
            {best_windows.map((w) => (
              <li key={w.start_local} className="flex items-center justify-between rounded-lg border border-green-500/30 bg-green-500/10 px-3 py-2 text-sm">
                <span className="font-medium">{range(w.start_local, w.end_local)}</span>
                <span className="tabular text-xs text-muted">avg strain {Math.round(w.avg_strain)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <Empty>No clearly green windows in the next 48 hours.</Empty>
        )}
      </div>
      <div>
        <h3 className="mb-2 text-sm font-semibold text-lvl-red">⛔ Avoid big loads</h3>
        {avoid_windows.length ? (
          <ul className="space-y-2">
            {avoid_windows.map((w) => (
              <li key={w.start_local} className="flex items-center justify-between rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm">
                <span className="font-medium">{range(w.start_local, w.end_local)}</span>
                <span className="tabular text-xs text-muted">spike risk up to {pct(w.max_spike_prob)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <Empty>Nothing to avoid. The grid looks comfortable.</Empty>
        )}
      </div>
    </div>
  );
}
