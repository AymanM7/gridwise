import type { ReactNode } from "react";
import { Reveal } from "./motion";
import type { Level } from "../lib/types";
import { LEVEL_COLOR, LEVEL_TEXT } from "../lib/format";

/**
 * Section surface. `icon` is a lucide-react component element, e.g. icon={<Activity />}.
 * `eyebrow` is an optional small uppercase label above the title.
 */
export function Card({
  title,
  eyebrow,
  icon,
  right,
  children,
  className = "",
  id,
}: {
  title?: string;
  eyebrow?: string;
  icon?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <Reveal className="h-full min-w-0">
      <section id={id} className={`surface h-full min-w-0 scroll-mt-24 p-4 sm:p-6 ${className}`}>
        {(title || right) && (
          <header className="mb-5 flex items-start justify-between gap-3">
            <div className="flex min-w-0 items-center gap-3">
              {icon && (
                <span
                  aria-hidden
                  className="grid h-8 w-8 shrink-0 place-items-center rounded-[10px] border border-line-strong bg-gradient-to-b from-panel-3 to-panel-2 text-muted shadow-[inset_0_1px_0_rgba(255,255,255,0.06)] [&>svg]:h-4 [&>svg]:w-4"
                >
                  {icon}
                </span>
              )}
              <div className="min-w-0">
                {eyebrow && <Eyebrow className="mb-0.5">{eyebrow}</Eyebrow>}
                {title && <h2 className="truncate text-[15px] font-semibold tracking-tight text-text sm:text-base">{title}</h2>}
              </div>
            </div>
            {right && <div className="shrink-0">{right}</div>}
          </header>
        )}
        {children}
      </section>
    </Reveal>
  );
}

/** Small-caps muted label used above titles and numbers. */
export function Eyebrow({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`text-[11px] font-medium uppercase tracking-[0.14em] text-[#7d838e] ${className}`}>{children}</div>;
}

export function Skeleton({ className = "h-40" }: { className?: string }) {
  return <div className={`skeleton rounded-xl ${className}`} aria-hidden />;
}

export function Loading({ label = "Loading", className = "h-40" }: { label?: string; className?: string }) {
  return (
    <div role="status" aria-live="polite">
      <span className="sr-only">{label}…</span>
      <Skeleton className={className} />
    </div>
  );
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-lvl-red/25 bg-lvl-red/[0.06] px-4 py-3 text-sm text-rose-100"
    >
      <span className="flex min-w-0 items-center gap-2.5">
        <span aria-hidden className="h-1.5 w-1.5 shrink-0 rounded-full bg-lvl-red" />
        {message}
      </span>
      {onRetry && (
        <button
          onClick={onRetry}
          className="rounded-lg border border-line-strong bg-panel-2 px-3 py-1 text-xs font-medium text-text transition-colors hover:border-white/20 hover:bg-panel-3"
        >
          Retry
        </button>
      )}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-line-strong bg-white/[0.01] px-4 py-6 text-center text-sm leading-relaxed text-muted">
      {children}
    </div>
  );
}

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "accent" | "warn" }) {
  const cls =
    tone === "accent"
      ? "border-accent/25 bg-accent/[0.08] text-sky-200"
      : tone === "warn"
        ? "border-lvl-yellow/25 bg-lvl-yellow/[0.08] text-amber-200"
        : "border-line-strong bg-panel-2 text-muted";
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium tracking-wide ${cls}`}>
      {children}
    </span>
  );
}

/** Level chip: tinted, with a colored dot and the text label (color is never the only signal). */
export function LevelPill({ level }: { level: Level }) {
  const c = LEVEL_COLOR[level];
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-semibold"
      style={{ color: c, borderColor: `${c}40`, background: `${c}14` }}
    >
      <span aria-hidden className="h-1.5 w-1.5 rounded-full" style={{ background: c, boxShadow: `0 0 8px ${c}` }} />
      {LEVEL_TEXT[level]}
    </span>
  );
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: string }) {
  return (
    <div className="rounded-xl border border-line bg-panel-2/70 p-3.5 transition-colors hover:border-line-strong">
      <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-[#7d838e]">{label}</div>
      <div className="tabular mt-1.5 text-xl font-semibold tracking-tight" style={tone ? { color: tone } : undefined}>
        {value}
      </div>
      {sub && <div className="mt-0.5 text-xs text-muted">{sub}</div>}
    </div>
  );
}

export const tooltipStyle = {
  contentStyle: {
    background: "rgba(20,23,28,0.92)",
    backdropFilter: "blur(8px)",
    border: "1px solid rgba(255,255,255,0.1)",
    boxShadow: "0 12px 32px -12px rgba(0,0,0,0.7)",
    borderRadius: 12,
    color: "#eceef1",
    fontSize: 12,
    padding: "8px 10px",
  },
  labelStyle: { color: "#e8eaed", fontWeight: 600 },
  itemStyle: { color: "#e8eaed" },
};

export const axisProps = {
  stroke: "rgba(255,255,255,0.08)",
  tick: { fill: "#7d838e", fontSize: 11 },
  axisLine: false,
  tickLine: false,
};
