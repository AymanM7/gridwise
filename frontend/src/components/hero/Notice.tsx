import type { ReactNode } from "react";

/** Slim status notice (demo / offline / stale). Tone tints only the icon well and a hairline. */
export default function Notice({
  tone = "info",
  icon,
  children,
  alert = false,
}: {
  tone?: "info" | "warn";
  icon: ReactNode;
  children: ReactNode;
  alert?: boolean;
}) {
  const well =
    tone === "warn" ? "border-lvl-yellow/30 bg-lvl-yellow/10 text-lvl-yellow" : "border-accent/30 bg-accent/10 text-accent";
  const edge = tone === "warn" ? "from-lvl-yellow/40" : "from-accent/40";
  return (
    <div
      role={alert ? "alert" : "status"}
      className="relative flex items-start gap-3 overflow-hidden rounded-xl border border-line bg-panel/80 px-3 py-2.5 text-[13px] leading-relaxed text-muted backdrop-blur sm:items-center"
    >
      <span aria-hidden className={`absolute inset-y-0 left-0 w-px bg-gradient-to-b ${edge} to-transparent`} />
      <span
        aria-hidden
        className={`grid h-6 w-6 shrink-0 place-items-center rounded-md border [&>svg]:h-3.5 [&>svg]:w-3.5 ${well}`}
      >
        {icon}
      </span>
      <span className="min-w-0">{children}</span>
    </div>
  );
}
