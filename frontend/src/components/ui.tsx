import type { ReactNode } from "react";
import type { Level } from "../lib/types";
import { LEVEL_COLOR, LEVEL_TEXT } from "../lib/format";

export function Card({
  title,
  icon,
  right,
  children,
  className = "",
  id,
}: {
  title?: string;
  icon?: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section id={id} className={`min-w-0 rounded-2xl border border-line bg-panel p-4 sm:p-5 ${className}`}>
      {(title || right) && (
        <header className="mb-3 flex items-center justify-between gap-3">
          {title && (
            <h2 className="flex items-center gap-2 text-base font-semibold tracking-tight sm:text-lg">
              {icon && <span aria-hidden>{icon}</span>}
              {title}
            </h2>
          )}
          {right}
        </header>
      )}
      {children}
    </section>
  );
}

export function Skeleton({ className = "h-40" }: { className?: string }) {
  return <div className={`animate-pulse rounded-xl bg-panel-2 ${className}`} aria-hidden />;
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
    <div role="alert" className="flex items-center justify-between gap-3 rounded-xl border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-200">
      <span>{message}</span>
      {onRetry && (
        <button onClick={onRetry} className="rounded-lg border border-red-400/50 px-3 py-1 font-medium hover:bg-red-500/20">
          Retry
        </button>
      )}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-xl border border-dashed border-line p-4 text-center text-sm text-muted">{children}</div>;
}

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "accent" | "warn" }) {
  const cls =
    tone === "accent"
      ? "border-sky-400/40 bg-sky-400/10 text-sky-200"
      : tone === "warn"
        ? "border-amber-400/40 bg-amber-400/10 text-amber-200"
        : "border-line bg-panel-2 text-muted";
  return <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${cls}`}>{children}</span>;
}

export function LevelPill({ level }: { level: Level }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold text-black"
      style={{ background: LEVEL_COLOR[level] }}
    >
      {LEVEL_TEXT[level]}
    </span>
  );
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: string }) {
  return (
    <div className="rounded-xl border border-line bg-panel-2 p-3">
      <div className="text-xs text-muted">{label}</div>
      <div className="tabular mt-1 text-xl font-semibold" style={tone ? { color: tone } : undefined}>
        {value}
      </div>
      {sub && <div className="mt-0.5 text-xs text-muted">{sub}</div>}
    </div>
  );
}

export const tooltipStyle = {
  contentStyle: {
    background: "#181b21",
    border: "1px solid #262a32",
    borderRadius: 12,
    color: "#e8eaed",
    fontSize: 12,
  },
  labelStyle: { color: "#e8eaed", fontWeight: 600 },
  itemStyle: { color: "#e8eaed" },
};

export const axisProps = {
  stroke: "#3a3f48",
  tick: { fill: "#9aa1ac", fontSize: 11 },
  tickLine: false,
};
