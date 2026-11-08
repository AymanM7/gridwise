"use client";

import { useMemo, useRef, useState, type KeyboardEvent } from "react";
import { MousePointerClick, TriangleExclamationPoint } from "lucide-react";
import type { ForecastHour, Level } from "../lib/types";
import { LEVEL_COLOR, LEVEL_TEXT, dayHourLabel, gw, hourLabel, localHour, pct, shortDay } from "../lib/format";
import { AnimatePresence, EASE_OUT, LayoutGroup, motion } from "./motion";
import { LevelPill } from "./ui";

const LEVELS: Level[] = ["green", "yellow", "red"];
const RANGE: Record<Level, string> = { green: "<60", yellow: "60–85", red: ">85" };
const H = 3600_000;

interface Row extends ForecastHour {
  i: number;
  t: number;
  hl: boolean;
}

function sameT(a: string | null, t: number) {
  return a != null && new Date(a).getTime() === t;
}

export default function StrainTimeline({
  hours,
  selected,
  onSelect,
  highlight,
}: {
  hours: ForecastHour[];
  selected: string | null;
  onSelect: (ts: string) => void;
  highlight: string[];
}) {
  const [hover, setHover] = useState<number | null>(null);
  const [now] = useState(() => Date.now());
  const btns = useRef<(HTMLButtonElement | null)[]>([]);

  const hlSet = useMemo(() => new Set(highlight.map((t) => new Date(t).getTime())), [highlight]);
  const hlKey = highlight.join("|");
  const rows: Row[] = useMemo(
    () =>
      hours.map((h, i) => {
        const t = new Date(h.target_ts).getTime();
        return { ...h, i, t, hl: hlSet.has(t) };
      }),
    [hours, hlSet],
  );
  const n = rows.length;
  const anyHl = hlSet.size > 0;
  const selIdx = rows.findIndex((r) => sameT(selected, r.t));

  // Y domain in MW, snapped to 5 GW.
  const { d0, d1, yTicks } = useMemo(() => {
    const lo = Math.min(...rows.map((r) => r.band_low_mw ?? r.net_load_mw ?? Infinity));
    const hi = Math.max(...rows.map((r) => r.band_high_mw ?? r.net_load_mw ?? -Infinity));
    const a = Math.floor((lo * 0.9) / 5000) * 5000;
    const b = Math.ceil((hi * 1.02) / 5000) * 5000;
    const ticks: number[] = [];
    for (let v = a; v <= b; v += 5000) ticks.push(v);
    return { d0: a, d1: b, yTicks: ticks.length <= 6 ? ticks : ticks.filter((_, i) => i % 2 === 0) };
  }, [rows]);
  const yPct = (mw: number) => Math.max(0, Math.min(100, ((mw - d0) / (d1 - d0)) * 100));
  const xPct = (i: number) => ((i + 0.5) / n) * 100;

  const bandPath = (() => {
    const pts = rows.filter((r) => r.band_low_mw != null && r.band_high_mw != null);
    if (pts.length < 2) return null;
    const top = pts.map((r) => `${r.i + 0.5},${100 - yPct(r.band_high_mw!)}`);
    const bot = [...pts].reverse().map((r) => `${r.i + 0.5},${100 - yPct(r.band_low_mw!)}`);
    return {
      area: `M${top.join("L")}L${bot.join("L")}Z`,
      hi: `M${top.join("L")}`,
      lo: `M${[...bot].reverse().join("L")}`,
    };
  })();

  const midnights = rows.filter((r) => r.i > 0 && localHour(r.target_ts) === 0);
  const xLabels = rows.filter((r) => localHour(r.target_ts) % 6 === 0);
  const nowPos = n ? (now - rows[0].t) / H : -1;
  const showNow = nowPos >= 0 && nowPos <= n;

  function move(e: KeyboardEvent) {
    const cur = selIdx >= 0 ? selIdx : 0;
    const next =
      e.key === "ArrowRight" ? cur + 1 : e.key === "ArrowLeft" ? cur - 1 : e.key === "Home" ? 0 : e.key === "End" ? n - 1 : null;
    if (next == null) return;
    e.preventDefault();
    const k = Math.max(0, Math.min(n - 1, next));
    onSelect(rows[k].target_ts);
    btns.current[k]?.focus();
  }

  const tip = hover != null ? rows[hover] : null;

  return (
    <LayoutGroup id="strain-timeline">
      <div className="space-y-4">
        {/* Legend */}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted">
          {LEVELS.map((l) => (
            <span key={l} className="inline-flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-[3px]" style={{ background: LEVEL_COLOR[l] }} aria-hidden />
              <span className="text-text/90">{LEVEL_TEXT[l]}</span>
              <span className="tabular text-[#7d838e]">{RANGE[l]}</span>
            </span>
          ))}
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-4 rounded-[3px] border border-white/15 bg-white/10" aria-hidden />
            P10–P90 band
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-0 w-3 border-t-2 border-dotted border-white/60" aria-hidden />
            Uncertain
          </span>
          <AnimatePresence>
            {anyHl && (
              <motion.span
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.9 }}
                className="inline-flex items-center gap-1.5 rounded-full border border-accent/30 bg-accent/10 px-2 py-0.5 font-medium text-accent"
              >
                <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden />
                {hlSet.size} hour{hlSet.size === 1 ? "" : "s"} suggested by chat
              </motion.span>
            )}
          </AnimatePresence>
        </div>

        <div className="grid grid-cols-[2.25rem_minmax(0,1fr)] gap-x-2 sm:grid-cols-[2.75rem_minmax(0,1fr)] sm:gap-x-3">
          {/* ── Row 1: tappable strip ── */}
          <div className="self-center text-right text-[10px] font-medium uppercase tracking-[0.12em] text-[#7d838e]">Hour</div>
          <div
            role="listbox"
            aria-label="Hourly strain, next 48 hours. Use arrow keys to move between hours."
            onKeyDown={move}
            onMouseLeave={() => setHover(null)}
            className="relative grid gap-[2px] pt-2 sm:gap-[3px]"
            style={{ gridTemplateColumns: `repeat(${n}, minmax(0, 1fr))` }}
          >
            {rows.map((r) => {
              const isSel = r.i === selIdx;
              const dim = anyHl && !r.hl && !isSel;
              const c = LEVEL_COLOR[r.level];
              return (
                <button
                  key={r.target_ts}
                  ref={(el) => {
                    btns.current[r.i] = el;
                  }}
                  role="option"
                  aria-selected={isSel}
                  tabIndex={isSel || (selIdx < 0 && r.i === 0) ? 0 : -1}
                  aria-label={`${dayHourLabel(r.target_ts)}: ${LEVEL_TEXT[r.level]}, strain ${Math.round(r.strain_index)}, spike risk ${pct(r.spike_prob)}${r.low_confidence ? ", uncertain" : ""}${r.hl ? ", suggested by chat" : ""}`}
                  onClick={() => onSelect(r.target_ts)}
                  onMouseEnter={() => setHover(r.i)}
                  onFocus={() => setHover(r.i)}
                  onBlur={() => setHover(null)}
                  className="group relative h-8 rounded-[3px] outline-none focus-visible:z-10 focus-visible:ring-2 focus-visible:ring-accent sm:h-9 sm:rounded-[5px]"
                >
                  <motion.span
                    aria-hidden
                    className="absolute inset-0 rounded-[inherit] transition-[filter] duration-200 group-hover:brightness-125"
                    style={{ background: `linear-gradient(180deg, ${c} 0%, ${c}b3 100%)` }}
                    initial={{ opacity: 0, scaleY: 0.4 }}
                    animate={{ opacity: dim ? 0.3 : 1, scaleY: 1 }}
                    transition={{ duration: 0.45, ease: EASE_OUT, delay: 0.1 + r.i * 0.01 }}
                  />
                  {r.low_confidence && (
                    <span
                      aria-hidden
                      className="absolute inset-x-[15%] -top-[5px] border-t-2 border-dotted border-white/70"
                    />
                  )}
                  {r.hl && (
                    <motion.span
                      key={hlKey}
                      aria-hidden
                      className="absolute -inset-[2px] rounded-[6px] ring-2 ring-accent shadow-[0_0_14px_rgba(125,211,252,0.55)]"
                      initial={{ opacity: 0, scale: 1.5 }}
                      animate={{ opacity: 1, scale: 1 }}
                      transition={{ type: "spring", stiffness: 360, damping: 22, delay: r.i * 0.015 }}
                    />
                  )}
                  {isSel && (
                    <motion.span
                      layoutId="strip-sel"
                      aria-hidden
                      className="absolute -inset-[3px] rounded-[7px] ring-2 ring-white"
                      style={{ boxShadow: `0 0 16px ${c}aa` }}
                      transition={{ type: "spring", stiffness: 500, damping: 38 }}
                    />
                  )}
                </button>
              );
            })}
          </div>

          {/* ── Row 2: y-axis + plot ── */}
          <div className="relative mt-4 h-52 sm:h-64 lg:h-80" aria-hidden>
            {yTicks.map((v) => (
              <span
                key={v}
                className="tabular absolute right-0 translate-y-1/2 text-[10px] leading-none text-[#7d838e] sm:text-[11px]"
                style={{ bottom: `${yPct(v)}%` }}
              >
                {v / 1000}
                <span className="hidden sm:inline"> GW</span>
              </span>
            ))}
          </div>
          <div className="relative mt-4 h-52 sm:h-64 lg:h-80" onMouseLeave={() => setHover(null)}>
            {/* grid */}
            {yTicks.map((v) => (
              <div key={v} aria-hidden className="absolute inset-x-0 h-px bg-white/[0.05]" style={{ bottom: `${yPct(v)}%` }} />
            ))}

            {/* P10–P90 band */}
            {bandPath && (
              <motion.svg
                aria-hidden
                viewBox={`0 0 ${n} 100`}
                preserveAspectRatio="none"
                className="pointer-events-none absolute inset-0 h-full w-full"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.8, ease: EASE_OUT, delay: 0.5 }}
              >
                <defs>
                  <linearGradient id="band-fill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#ffffff" stopOpacity={0.13} />
                    <stop offset="100%" stopColor="#ffffff" stopOpacity={0.04} />
                  </linearGradient>
                </defs>
                <path d={bandPath.area} fill="url(#band-fill)" />
                <path d={bandPath.hi} fill="none" stroke="rgba(255,255,255,0.22)" strokeWidth={1} vectorEffect="non-scaling-stroke" strokeDasharray="2 3" />
                <path d={bandPath.lo} fill="none" stroke="rgba(255,255,255,0.14)" strokeWidth={1} vectorEffect="non-scaling-stroke" strokeDasharray="2 3" />
              </motion.svg>
            )}

            {/* day separators */}
            {midnights.map((m) => (
              <div key={m.target_ts} aria-hidden className="pointer-events-none absolute inset-y-0 w-px" style={{ left: `${(m.i / n) * 100}%` }}>
                <div className="h-full w-px bg-[repeating-linear-gradient(to_bottom,rgba(255,255,255,0.18)_0_3px,transparent_3px_7px)]" />
                <span className="absolute -top-0.5 left-1.5 whitespace-nowrap rounded bg-panel/90 px-1 text-[10px] font-semibold uppercase tracking-[0.1em] text-muted">
                  {shortDay(m.target_ts)}
                </span>
              </div>
            ))}

            {/* now marker */}
            {showNow && (
              <div aria-hidden className="pointer-events-none absolute inset-y-0 z-10" style={{ left: `${(nowPos / n) * 100}%` }}>
                <div className="h-full w-px bg-gradient-to-b from-accent to-accent/0" />
                <span className="absolute -left-[3px] -top-[3px] h-[7px] w-[7px] rounded-full bg-accent shadow-[0_0_8px_var(--accent)]" />
                <span className="absolute left-2 top-3 text-[10px] font-semibold uppercase tracking-[0.12em] text-accent">Now</span>
              </div>
            )}

            {/* bars */}
            <div className="absolute inset-0 grid gap-[2px] sm:gap-[3px]" style={{ gridTemplateColumns: `repeat(${n}, minmax(0, 1fr))` }}>
              {rows.map((r) => {
                const isSel = r.i === selIdx;
                const dim = anyHl && !r.hl && !isSel;
                const c = LEVEL_COLOR[r.level];
                const h = r.net_load_mw != null ? yPct(r.net_load_mw) : 0;
                return (
                  <div
                    key={r.target_ts}
                    role="presentation"
                    onMouseEnter={() => setHover(r.i)}
                    onClick={() => onSelect(r.target_ts)}
                    className="relative h-full cursor-pointer"
                  >
                    {isSel && (
                      <motion.div
                        layoutId="chart-sel"
                        className="absolute -inset-x-[2px] inset-y-0 rounded-md border border-white/10 bg-white/[0.045]"
                        transition={{ type: "spring", stiffness: 500, damping: 40 }}
                      />
                    )}
                    {hover === r.i && !isSel && <div className="absolute inset-0 rounded-md bg-white/[0.03]" />}
                    <motion.div
                      className="absolute inset-x-[12%] bottom-0 origin-bottom rounded-t-[3px] sm:rounded-t-[4px]"
                      style={{
                        height: `${h}%`,
                        background: `linear-gradient(180deg, ${c} 0%, ${c}cc 35%, ${c}26 100%)`,
                        boxShadow: isSel
                          ? `0 0 0 1.5px #fff, 0 0 18px ${c}99`
                          : r.hl
                            ? `0 0 0 1.5px var(--accent), 0 0 14px rgba(125,211,252,0.45)`
                            : undefined,
                      }}
                      initial={{ scaleY: 0, opacity: 0 }}
                      animate={{ scaleY: 1, opacity: dim ? 0.28 : 1 }}
                      transition={{
                        scaleY: { duration: 0.6, ease: EASE_OUT, delay: 0.15 + r.i * 0.012 },
                        opacity: { duration: 0.3 },
                      }}
                    />
                    {r.hl && (
                      <motion.span
                        key={hlKey}
                        aria-hidden
                        className="absolute left-1/2 h-1.5 w-1.5 -translate-x-1/2 rounded-full bg-accent shadow-[0_0_8px_var(--accent)]"
                        style={{ bottom: `calc(${h}% + 6px)` }}
                        initial={{ opacity: 0, y: -10 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ type: "spring", stiffness: 400, damping: 18, delay: 0.1 + r.i * 0.015 }}
                      />
                    )}
                  </div>
                );
              })}
            </div>

            {/* tooltip */}
            <AnimatePresence>
              {tip && (
                <motion.div
                  key="tip"
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: 4 }}
                  transition={{ duration: 0.15 }}
                  className="pointer-events-none absolute top-6 z-20 w-56"
                  style={{
                    left: `${xPct(tip.i)}%`,
                    transform: `translateX(${tip.i < n * 0.2 ? "-8%" : tip.i > n * 0.8 ? "-92%" : "-50%"})`,
                  }}
                >
                  <TipCard r={tip} />
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {/* ── Row 3: x labels ── */}
          <div />
          <div className="relative mt-2 h-4" aria-hidden>
            {xLabels.map((r) => (
              <span
                key={r.target_ts}
                className={`tabular absolute -translate-x-1/2 whitespace-nowrap text-[10px] sm:text-[11px] ${
                  localHour(r.target_ts) === 0 ? "font-medium text-muted" : "text-[#7d838e]"
                }`}
                style={{ left: `${xPct(r.i)}%` }}
              >
                {localHour(r.target_ts) === 0 ? "12 am" : hourLabel(r.target_ts)}
              </span>
            ))}
          </div>
        </div>

        <Summary rows={rows} onSelect={onSelect} />

        <p className="flex items-center gap-1.5 text-xs text-muted">
          <MousePointerClick className="h-3.5 w-3.5" aria-hidden />
          Tap any hour, or use the arrow keys on the strip, to see why it is that color.
        </p>
      </div>
    </LayoutGroup>
  );
}

function TipCard({ r }: { r: Row }) {
  return (
    <div className="rounded-xl border border-white/10 bg-[#14171c]/95 p-3 text-xs shadow-[0_16px_40px_-12px_rgba(0,0,0,0.8)] backdrop-blur-md">
      <div className="flex items-center justify-between gap-2">
        <span className="font-semibold text-text">{dayHourLabel(r.target_ts)}</span>
        <LevelPill level={r.level} />
      </div>
      <dl className="tabular mt-2.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
        <dt className="text-muted">Strain</dt>
        <dd className="text-right text-text">{Math.round(r.strain_index)}/100</dd>
        <dt className="text-muted">Net load</dt>
        <dd className="text-right text-text">{gw(r.net_load_mw)}</dd>
        <dt className="text-muted">Likely range</dt>
        <dd className="text-right text-text">
          {gw(r.band_low_mw)} – {gw(r.band_high_mw)}
        </dd>
        <dt className="text-muted">Spike risk</dt>
        <dd className="text-right text-text">{pct(r.spike_prob)}</dd>
      </dl>
      {r.low_confidence && (
        <div className="mt-2 flex items-center gap-1.5 text-amber-200">
          <TriangleExclamationPoint className="h-3.5 w-3.5" aria-hidden />
          Uncertain: weather forecast is shifting
        </div>
      )}
      {r.hl && <div className="mt-2 font-medium text-accent">Suggested by chat</div>}
    </div>
  );
}

function Summary({ rows, onSelect }: { rows: Row[]; onSelect: (ts: string) => void }) {
  if (!rows.length) return null;
  const peak = rows.reduce((m, r) => (r.strain_index > m.strain_index ? r : m), rows[0]);
  const calm = rows.reduce((m, r) => (r.strain_index < m.strain_index ? r : m), rows[0]);
  const red = rows.filter((r) => r.level === "red").length;
  const unsure = rows.filter((r) => r.low_confidence).length;
  const items: { k: string; v: string; sub: string; level?: Level; ts?: string }[] = [
    { k: "Tightest hour", v: dayHourLabel(peak.target_ts), sub: `strain ${Math.round(peak.strain_index)}`, level: peak.level, ts: peak.target_ts },
    { k: "Calmest hour", v: dayHourLabel(calm.target_ts), sub: `strain ${Math.round(calm.strain_index)}`, level: calm.level, ts: calm.target_ts },
    { k: "Tight hours", v: `${red} of ${rows.length}`, sub: red ? "strain above 85" : "none ahead" },
    { k: "Uncertain hours", v: `${unsure}`, sub: unsure ? "weather still shifting" : "forecast is settled" },
  ];
  return (
    <div className="grid grid-cols-2 gap-2 border-t border-line pt-4 sm:grid-cols-4 sm:gap-3">
      {items.map((it) => {
        const body = (
          <>
            <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-[#8b929e]">{it.k}</div>
            <div className="tabular mt-1 flex items-center gap-1.5 text-sm font-semibold text-text">
              {it.level && <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: LEVEL_COLOR[it.level] }} />}
              {it.v}
            </div>
            <div className="tabular mt-0.5 text-xs text-muted">{it.sub}</div>
          </>
        );
        const cls = "rounded-xl border border-line bg-white/[0.02] px-3 py-2.5 text-left";
        return it.ts ? (
          <button
            key={it.k}
            onClick={() => onSelect(it.ts!)}
            aria-label={`${it.k}: ${it.v}, ${it.sub}. Show why.`}
            className={`${cls} transition-[border-color,transform] duration-200 hover:-translate-y-px hover:border-line-strong`}
          >
            {body}
          </button>
        ) : (
          <div key={it.k} className={cls}>
            {body}
          </div>
        );
      })}
    </div>
  );
}
