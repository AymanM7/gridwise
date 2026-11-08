import type { Level } from "./types";

export const TZ = "America/Chicago";

export const LEVEL_COLOR: Record<Level, string> = {
  green: "#22c55e",
  yellow: "#eab308",
  red: "#ef4444",
};

export const LEVEL_TEXT: Record<Level, string> = {
  green: "Normal",
  yellow: "Elevated",
  red: "Tight",
};

const hourFmt = new Intl.DateTimeFormat("en-US", { timeZone: TZ, hour: "numeric" });
const dayHourFmt = new Intl.DateTimeFormat("en-US", { timeZone: TZ, weekday: "short", hour: "numeric" });
const dayFmt = new Intl.DateTimeFormat("en-US", { timeZone: TZ, weekday: "long", month: "long", day: "numeric" });
const shortDayFmt = new Intl.DateTimeFormat("en-US", { timeZone: TZ, weekday: "short", month: "short", day: "numeric" });
const timeFmt = new Intl.DateTimeFormat("en-US", {
  timeZone: TZ,
  weekday: "short",
  hour: "numeric",
  minute: "2-digit",
  timeZoneName: "short",
});
const hourNum = new Intl.DateTimeFormat("en-US", { timeZone: TZ, hour: "numeric", hourCycle: "h23" });

/** "5 PM" -> "5 pm" */
export function hourLabel(iso: string): string {
  return hourFmt.format(new Date(iso)).replace(" AM", " am").replace(" PM", " pm");
}

/** "Sat 5 pm" */
export function dayHourLabel(iso: string): string {
  return dayHourFmt.format(new Date(iso)).replace(" AM", " am").replace(" PM", " pm");
}

export function longDay(d: Date): string {
  return dayFmt.format(d);
}

export function shortDay(iso: string): string {
  // Dates like "2026-11-07" are calendar days; anchor at noon UTC so the TZ shift never changes the day.
  const d = iso.length === 10 ? new Date(`${iso}T12:00:00Z`) : new Date(iso);
  return shortDayFmt.format(d);
}

export function timestampLabel(iso: string): string {
  return timeFmt.format(new Date(iso));
}

export function localHour(iso: string): number {
  return Number(hourNum.format(new Date(iso))) % 24;
}

export function tomorrowLocal(now = new Date()): Date {
  return new Date(now.getTime() + 24 * 3600 * 1000);
}

export function gw(mw: number | null | undefined, digits = 1): string {
  if (mw == null || Number.isNaN(mw)) return "–";
  return `${(mw / 1000).toFixed(digits)} GW`;
}

export function pct(p: number | null | undefined, digits = 0): string {
  if (p == null || Number.isNaN(p)) return "–";
  return `${(p * 100).toFixed(digits)}%`;
}

export function ageMinutes(iso: string | null | undefined, now = Date.now()): number | null {
  if (!iso) return null;
  return Math.max(0, Math.round((now - new Date(iso).getTime()) / 60000));
}

export function ageLabel(min: number | null): string {
  if (min == null) return "unknown";
  if (min < 60) return `${min} min ago`;
  const h = Math.floor(min / 60);
  if (h < 48) return `${h} h ago`;
  return `${Math.floor(h / 24)} days ago`;
}

export function levelOf(strain: number): Level {
  if (strain < 60) return "green";
  if (strain <= 85) return "yellow";
  return "red";
}

export function sameInstant(a: string, b: string): boolean {
  return new Date(a).getTime() === new Date(b).getTime();
}
