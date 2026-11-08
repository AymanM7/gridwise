"use client";

import { useId } from "react";
import { SPRING, motion } from "../motion";

/**
 * Stepped range slider. A native <input type="range"> sits on top (transparent) so keyboard,
 * screen readers and touch all work natively; the visual track / fill / thumb / bubble are drawn below.
 */
export function StepSlider({
  label,
  steps,
  value,
  onChange,
  format,
  valueText,
}: {
  label: string;
  steps: number[];
  value: number;
  onChange: (v: number) => void;
  format: (v: number) => string;
  valueText: (v: number) => string;
}) {
  const id = useId();
  const idx = Math.max(0, steps.indexOf(value));
  const frac = steps.length > 1 ? idx / (steps.length - 1) : 0;
  // Native thumbs travel over (width - thumb); mirror that with an 8px inset on each side.
  const left = `calc(8px + (100% - 16px) * ${frac})`;

  return (
    <div className="min-w-0">
      <label htmlFor={id} className="block text-[11px] font-medium uppercase tracking-[0.14em] text-muted">
        {label}
      </label>

      <div className="relative mt-2 h-10">
        {/* value bubble */}
        <span
          aria-hidden
          style={{ left }}
          className="tabular pointer-events-none absolute top-0 -translate-x-1/2 transition-[left] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] whitespace-nowrap rounded-md border border-line-strong bg-panel-3 px-1.5 py-0.5 text-[11px] font-medium text-text shadow-[0_6px_16px_-8px_rgba(0,0,0,0.8)]"
        >
          {format(value)}
        </span>

        {/* track */}
        <div aria-hidden className="absolute inset-x-0 bottom-[7px] h-1.5 rounded-full bg-panel-3">
          <div
            className="absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-sky-300/30 to-accent transition-[width] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]"
            style={{ width: left }}
          />
          {/* step ticks */}
          {steps.map((s, i) => (
            <span
              key={s}
              className={`absolute top-1/2 h-1 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full ${
                i <= idx ? "bg-black/40" : "bg-white/15"
              }`}
              style={{ left: `calc(8px + (100% - 16px) * ${steps.length > 1 ? i / (steps.length - 1) : 0})` }}
            />
          ))}
        </div>

        <input
          id={id}
          type="range"
          min={0}
          max={steps.length - 1}
          step={1}
          value={idx}
          onChange={(e) => onChange(steps[Number(e.target.value)])}
          aria-valuetext={valueText(value)}
          className="peer absolute inset-x-0 bottom-0 z-10 h-5 w-full cursor-pointer appearance-none bg-transparent opacity-0"
        />

        {/* thumb */}
        <span
          aria-hidden
          style={{ left }}
          className="pointer-events-none absolute bottom-[2px] h-4 w-4 -translate-x-1/2 rounded-full border-2 border-accent bg-text shadow-[0_0_0_4px_rgba(125,211,252,0.12),0_2px_6px_rgba(0,0,0,0.6)] transition-[left,box-shadow] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] peer-hover:shadow-[0_0_0_6px_rgba(125,211,252,0.18),0_2px_6px_rgba(0,0,0,0.6)] peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-accent"
        />
      </div>

      <div aria-hidden className="tabular mt-1 flex justify-between text-[11px] text-muted">
        <span>{format(steps[0])}</span>
        <span>{format(steps[steps.length - 1])}</span>
      </div>
    </div>
  );
}

/** Segmented control built on native radio inputs (arrow keys work); the active pill slides. */
export function Segmented({
  label,
  name,
  options,
  value,
  onChange,
}: {
  label: string;
  name: string;
  options: { v: string; l: string; hint?: string }[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <fieldset className="min-w-0">
      <legend className="mb-2 text-[11px] font-medium uppercase tracking-[0.14em] text-muted">{label}</legend>
      <div className="flex gap-1 rounded-xl border border-line bg-panel-2/60 p-1">
        {options.map((o) => {
          const on = o.v === value;
          return (
            <label
              key={o.v}
              className={`relative flex min-w-0 flex-1 cursor-pointer flex-col items-center justify-center rounded-lg px-2 py-1.5 text-center transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-1 has-[:focus-visible]:outline-accent ${
                on ? "text-text" : "text-muted hover:text-text"
              }`}
            >
              <input
                type="radio"
                name={name}
                value={o.v}
                checked={on}
                onChange={() => onChange(o.v)}
                className="sr-only"
              />
              {on && (
                <motion.span
                  layoutId={`seg-${name}`}
                  className="absolute inset-0 rounded-lg border border-line-strong bg-panel-3 shadow-[0_1px_0_0_rgba(255,255,255,0.05)_inset]"
                  transition={SPRING}
                />
              )}
              <span className="tabular relative truncate text-xs font-medium sm:text-[13px]">{o.l}</span>
              {o.hint && <span className="relative truncate text-[10px] text-muted">{o.hint}</span>}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
