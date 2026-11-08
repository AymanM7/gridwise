import type { Advice } from "../lib/types";
import { dayHourLabel, shortDay } from "../lib/format";
import { Badge, Empty } from "./ui";

const ICONS: Record<string, string> = {
  snowflake: "❄️",
  ac: "❄️",
  thermostat: "🌡️",
  shirt: "👕",
  laundry: "👕",
  dishwasher: "🍽️",
  car: "🚗",
  ev: "🚗",
  plug: "🔌",
  pool: "🏊",
  sun: "☀️",
  moon: "🌙",
  bolt: "⚡",
  alert: "⚠️",
  clock: "🕐",
  home: "🏠",
};

function iconFor(name: string): string {
  if (!name) return "💡";
  if (/[^\x00-\x7F]/.test(name)) return name; // already an emoji
  return ICONS[name.toLowerCase()] ?? "💡";
}

export function AdviceBadge({ by }: { by: Advice["generated_by"] }) {
  return by === "gemini" ? <Badge tone="accent">✨ Gemini</Badge> : <Badge>Rules</Badge>;
}

export default function AdvicePanel({ advice }: { advice: Advice }) {
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted">
        Plan for <span className="text-text">{shortDay(advice.date_local)}</span>
        {advice.generated_by === "rules" && " · Gemini was unavailable, so this plan is built from the best and worst hours."}
      </p>
      <p className="font-medium">{advice.headline}</p>
      {advice.tips.length ? (
        <ul className="space-y-2">
          {advice.tips.map((t, i) => (
            <li key={i} className="flex gap-3 rounded-lg bg-panel-2 px-3 py-2 text-sm">
              <span aria-hidden className="text-lg leading-5">
                {iconFor(t.icon)}
              </span>
              <div>
                <div>{t.text}</div>
                {t.window && <div className="mt-0.5 text-xs text-muted">🕐 {t.window}</div>}
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <Empty>No tips for this forecast.</Empty>
      )}
      {advice.best_hours.length > 0 && (
        <div className="text-xs text-muted">
          Greenest hours:{" "}
          <span className="text-text">
            {[...advice.best_hours]
              .slice(0, 6)
              .sort((a, b) => new Date(a).getTime() - new Date(b).getTime())
              .map((h) => dayHourLabel(h))
              .join(" · ")}
          </span>
        </div>
      )}
    </div>
  );
}
