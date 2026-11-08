"use client";

/**
 * Shared building blocks for the insight panels (advice, best hours, chat, ripple, report, history).
 * Grayscale + accent everywhere; strain colors only where they mean strain.
 */
import type { ReactNode } from "react";
import {
  Ban,
  BatteryCharging,
  Car,
  Clock,
  Flame,
  House,
  Lightbulb,
  Moon,
  PlugZap,
  Shirt,
  Snowflake,
  Sun,
  Thermometer,
  Utensils,
  Waves,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { AnimatedNumber } from "../motion";

/** Remove emoji / pictographs (and their joiners / variation selectors), then tidy whitespace. */
export function stripEmoji(s: string): string {
  return s
    .replace(/[\p{Extended_Pictographic}\u{1F1E6}-\u{1F1FF}\u{FE0F}\u{200D}\u{20E3}]/gu, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

const ICON_BY_KIND: Record<string, LucideIcon> = {
  snowflake: Snowflake,
  ac: Snowflake,
  cool: Snowflake,
  thermostat: Thermometer,
  heat: Flame,
  shirt: Shirt,
  laundry: Shirt,
  dishwasher: Utensils,
  car: Car,
  ev: Car,
  battery: BatteryCharging,
  plug: PlugZap,
  pool: Waves,
  sun: Sun,
  solar: Sun,
  moon: Moon,
  night: Moon,
  bolt: Zap,
  zap: Zap,
  alert: Ban,
  avoid: Ban,
  clock: Clock,
  home: House,
};

const ICON_BY_KEYWORD: [RegExp, LucideIcon][] = [
  [/\b(hold off|avoid|skip|don'?t)\b/i, Ban],
  [/\b(ev|car|charg)/i, Car],
  [/\b(laundry|washer|dryer)\b/i, Shirt],
  [/\b(pre-?cool|a\/?c|air condition|cool)/i, Snowflake],
  [/\b(thermostat|pre-?heat|heat)/i, Thermometer],
  [/\bdishwasher\b/i, Utensils],
  [/\bpool\b/i, Waves],
  [/\b(solar|sun|midday)\b/i, Sun],
  [/\b(night|overnight|late)\b/i, Moon],
];

/** Pick a lucide icon from the API's `icon` kind first, then from keywords in the text. */
export function adviceIcon(kind: string | null | undefined, text: string): LucideIcon {
  const k = (kind ?? "").toLowerCase().trim();
  if (k && ICON_BY_KIND[k]) return ICON_BY_KIND[k];
  for (const [re, icon] of ICON_BY_KEYWORD) if (re.test(text)) return icon;
  return Lightbulb;
}

/** Small-caps eyebrow label. */
export function Eyebrow({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`text-[11px] font-medium uppercase tracking-[0.14em] text-muted ${className}`}>{children}</div>
  );
}

/** Quiet neutral chip with an optional leading icon / dot. */
export function Chip({
  children,
  className = "",
  title,
}: {
  children: ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={`tabular inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-line bg-panel-2 px-2 py-0.5 text-[11px] font-medium text-muted ${className}`}
    >
      {children}
    </span>
  );
}

/** Legend chip: a swatch (dot, bar or dashed line) + label. */
export function LegendChip({
  color,
  label,
  shape = "dot",
}: {
  color: string;
  label: string;
  shape?: "dot" | "bar" | "line" | "dash";
}) {
  const sw =
    shape === "bar" ? (
      <span className="h-2.5 w-1.5 rounded-[2px]" style={{ background: color }} />
    ) : shape === "line" ? (
      <span className="h-0.5 w-3 rounded-full" style={{ background: color }} />
    ) : shape === "dash" ? (
      <span className="w-3 border-t border-dashed" style={{ borderColor: color }} />
    ) : (
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
    );
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-line px-2 py-0.5 text-[11px] text-muted">
      <span aria-hidden className="inline-flex items-center">
        {sw}
      </span>
      {label}
    </span>
  );
}

/**
 * Stat tile: eyebrow, big tweening number, optional footnote. Numbers tween on every change
 * (AnimatedNumber starts once the tile is in view and re-tweens whenever `value` changes).
 */
export function StatTile({
  label,
  value,
  format,
  display,
  sub,
  tone,
  icon,
  children,
  size = "md",
}: {
  label: string;
  value?: number | null;
  format?: (n: number) => string;
  /** Static text used instead of a tweened number (e.g. "none", "–"). */
  display?: ReactNode;
  sub?: ReactNode;
  tone?: string;
  icon?: ReactNode;
  children?: ReactNode;
  size?: "md" | "lg";
}) {
  return (
    <div className="group relative flex min-w-0 flex-col rounded-xl border border-line bg-panel-2/60 p-3 transition-colors duration-200 hover:border-line-strong sm:p-4">
      <div className="flex items-start justify-between gap-2">
        <Eyebrow className="leading-4">{label}</Eyebrow>
        {icon && (
          <span aria-hidden className="hidden text-faint sm:inline [&>svg]:h-3.5 [&>svg]:w-3.5">
            {icon}
          </span>
        )}
      </div>
      <div
        className={`tabular mt-2 font-semibold tracking-tight text-text ${
          size === "lg" ? "text-[28px] leading-8 sm:text-4xl sm:leading-10" : "text-2xl leading-8"
        }`}
        style={tone ? { color: tone } : undefined}
      >
        {display != null || value == null ? (display ?? "–") : <AnimatedNumber value={value} format={format} />}
      </div>
      {children}
      {sub && <div className="mt-1.5 text-xs leading-relaxed text-muted">{sub}</div>}
    </div>
  );
}

/** Glassy chart tooltip shell shared by the custom Recharts tooltips. */
export function TooltipShell({ title, children }: { title: ReactNode; children: ReactNode }) {
  return (
    <div className="min-w-[160px] rounded-xl border border-line-strong bg-[rgba(20,23,28,0.94)] px-3 py-2 text-xs shadow-[0_12px_32px_-12px_rgba(0,0,0,0.7)] backdrop-blur-md">
      <div className="mb-1.5 font-semibold text-text">{title}</div>
      <div className="space-y-1">{children}</div>
    </div>
  );
}

export function TooltipRow({ swatch, label, value }: { swatch: ReactNode; label: string; value: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="flex items-center gap-1.5 text-muted">
        <span aria-hidden className="inline-flex">
          {swatch}
        </span>
        {label}
      </span>
      <span className="tabular font-medium text-text">{value}</span>
    </div>
  );
}

export const ACCENT = "#7dd3fc";
export const MUTED = "#8b929e";
export const FAINT = "#5b616c";
