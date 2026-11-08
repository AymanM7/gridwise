import type { ReportCard as RC } from "../lib/types";
import { shortDay } from "../lib/format";
import { Badge, Empty, Stat } from "./ui";

function n(v: number | null | undefined, d = 1, suffix = "") {
  return v == null ? "–" : `${v.toFixed(d)}${suffix}`;
}

export default function ReportCard({ rc }: { rc: RC }) {
  const l = rc.latest;
  if (!l) return <Empty>No graded days yet. The report card fills in once yesterday&apos;s actuals arrive.</Empty>;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-sm text-muted">
        How did we do on <span className="text-text">{shortDay(l.date)}</span>?
        <Badge tone={l.source === "live" ? "accent" : "neutral"}>{l.source === "live" ? "Live forecast" : "Backtest"}</Badge>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label="Net-load error (MAPE)" value={n(l.mape, 1, "%")} />
        <Stat label="Demand error" value={n(l.demand_mape, 1, "%")} />
        <Stat
          label="Spike hours caught"
          value={l.spike_hours_actual ? `${l.spike_hours_caught} of ${l.spike_hours_actual}` : "none"}
          sub={l.spike_hours_actual ? undefined : "no spikes that day"}
        />
        <Stat label="Actuals inside band" value={n(l.band_coverage, 0, "%")} sub="target ≈ 80%" />
      </div>
      {rc.rows.length > 1 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[420px] text-left text-xs">
            <thead className="text-muted">
              <tr>
                <th className="py-1.5 font-medium">Day</th>
                <th className="font-medium">Error</th>
                <th className="font-medium">Demand err.</th>
                <th className="font-medium">Spikes caught</th>
                <th className="font-medium">In band</th>
              </tr>
            </thead>
            <tbody className="tabular">
              {rc.rows.map((r) => (
                <tr key={`${r.date}-${r.source}`} className="border-t border-line">
                  <td className="py-1.5">{shortDay(r.date)}</td>
                  <td>{n(r.mape, 1, "%")}</td>
                  <td>{n(r.demand_mape, 1, "%")}</td>
                  <td>{r.spike_hours_actual ? `${r.spike_hours_caught}/${r.spike_hours_actual}` : "–"}</td>
                  <td>{n(r.band_coverage, 0, "%")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {rc.note && <p className="text-xs text-muted">{rc.note}</p>}
    </div>
  );
}
