"use client";

import type { Level } from "../../lib/types";
import { LEVEL_COLOR, LEVEL_TEXT } from "../../lib/format";
import { AnimatedNumber, EASE_OUT, motion } from "../motion";

const SWEEP = 0.75; // 270° arc, gap at the bottom

/** 270° ring gauge for a 0–100 strain index, with the 60 / 85 level thresholds ticked. */
export default function StrainGauge({
  value,
  level,
  caption,
  size = 184,
}: {
  value: number;
  level: Level;
  caption?: string;
  size?: number;
}) {
  const c = LEVEL_COLOR[level];
  const r = 42;
  const frac = Math.max(0, Math.min(1, value / 100)) * SWEEP;
  const tick = (t: number) => {
    const a = ((135 + t * 270) * Math.PI) / 180;
    return { x1: 50 + Math.cos(a) * 34.5, y1: 50 + Math.sin(a) * 34.5, x2: 50 + Math.cos(a) * 37.5, y2: 50 + Math.sin(a) * 37.5 };
  };

  return (
    <div
      className="relative shrink-0"
      style={{ width: size, height: size }}
      role="img"
      aria-label={`Peak strain ${Math.round(value)} out of 100, ${LEVEL_TEXT[level]}`}
    >
      {/* soft level glow behind the ring */}
      <div
        aria-hidden
        className="absolute inset-[18%] rounded-full blur-2xl"
        style={{ background: `radial-gradient(circle, ${c}33, transparent 70%)` }}
      />
      <svg viewBox="0 0 100 100" className="relative h-full w-full" aria-hidden>
        <defs>
          <linearGradient id={`gauge-${level}`} x1="0" y1="1" x2="1" y2="0">
            <stop offset="0%" stopColor={c} stopOpacity={0.35} />
            <stop offset="100%" stopColor={c} />
          </linearGradient>
        </defs>
        <g transform="rotate(135 50 50)">
          <circle
            cx="50"
            cy="50"
            r={r}
            fill="none"
            stroke="rgba(255,255,255,0.07)"
            strokeWidth="6"
            strokeLinecap="round"
            pathLength={1}
            strokeDasharray={`${SWEEP} 1`}
          />
          <motion.circle
            cx="50"
            cy="50"
            r={r}
            fill="none"
            stroke={`url(#gauge-${level})`}
            strokeWidth="6"
            strokeLinecap="round"
            initial={{ pathLength: 0 }}
            animate={{ pathLength: frac }}
            transition={{ duration: 1.1, ease: EASE_OUT, delay: 0.15 }}
            style={{ filter: `drop-shadow(0 0 6px ${c}88)` }}
          />
        </g>
        {[0.6, 0.85].map((t) => (
          <line key={t} {...tick(t)} stroke="rgba(255,255,255,0.28)" strokeWidth="0.8" strokeLinecap="round" />
        ))}
      </svg>
      <div className="absolute inset-0 grid place-items-center">
        <div className="text-center">
          <div className="flex items-baseline justify-center gap-0.5">
            <AnimatedNumber value={value} className="text-[2.75rem] font-semibold leading-none tracking-[-0.04em] text-text" />
            <span className="text-sm text-muted">/100</span>
          </div>
          <div className="mt-1.5 text-[11px] font-medium uppercase tracking-[0.14em] text-[#8b929e]">Peak strain</div>
          {caption && <div className="tabular mt-0.5 text-xs font-medium" style={{ color: c }}>{caption}</div>}
        </div>
      </div>
    </div>
  );
}
