"use client";

import { Clock, Info, Sparkles } from "lucide-react";
import type { Advice } from "../lib/types";
import { dayHourLabel, shortDay } from "../lib/format";
import { Stagger, StaggerItem } from "./motion";
import { Empty } from "./ui";
import { Eyebrow, adviceIcon, stripEmoji } from "./insights/shared";

export function AdviceBadge({ by }: { by: Advice["generated_by"] }) {
  if (by === "gemini") {
    return (
      <span className="gw-gemini inline-flex shrink-0">
        <span className="inline-flex items-center gap-1 px-2 py-0.5 text-[11px] font-medium text-sky-100">
          <Sparkles aria-hidden className="h-3 w-3 text-accent" />
          Gemini
        </span>
      </span>
    );
  }
  return (
    <span className="inline-flex shrink-0 items-center rounded-full border border-line bg-panel-2 px-2 py-0.5 text-[11px] font-medium text-muted">
      Rules
    </span>
  );
}

export default function AdvicePanel({ advice }: { advice: Advice }) {
  const tips = advice.tips
    .map((t) => ({ ...t, text: stripEmoji(t.text), window: t.window ? stripEmoji(t.window) : null }))
    .filter((t) => t.text);
  const best = [...advice.best_hours]
    .slice(0, 6)
    .sort((a, b) => new Date(a).getTime() - new Date(b).getTime());

  return (
    <div className="space-y-5">
      <div>
        <Eyebrow>Plan for {shortDay(advice.date_local)}</Eyebrow>
        <p className="mt-2 text-[17px] font-semibold leading-snug tracking-tight text-text text-pretty">
          {stripEmoji(advice.headline)}
        </p>
        {advice.generated_by === "rules" && (
          <p className="mt-2 flex items-center gap-1.5 text-xs text-muted">
            <Info aria-hidden className="h-3.5 w-3.5 shrink-0" />
            Built from the forecast&apos;s best and worst hours (Gemini unavailable).
          </p>
        )}
      </div>

      {tips.length ? (
        <Stagger as="ol" className="relative space-y-1" stagger={0.07}>
          {/* timeline rail */}
          <span aria-hidden className="absolute bottom-5 left-[17px] top-5 w-px bg-line" />
          {tips.map((t, i) => {
            const Icon = adviceIcon(t.icon, t.text);
            return (
              <StaggerItem as="li" key={i} className="relative">
                <div className="group flex gap-3 rounded-xl px-0 py-2 transition-colors">
                  <span
                    aria-hidden
                    className="relative z-10 grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-line bg-panel-2 text-muted transition-colors duration-200 group-hover:border-line-strong group-hover:text-text"
                  >
                    <Icon className="h-4 w-4" strokeWidth={1.75} />
                  </span>
                  <div className="min-w-0 flex-1 pt-0.5">
                    <p className="text-sm leading-relaxed text-text/90 text-pretty">{t.text}</p>
                    {t.window && (
                      <span className="mt-1.5 inline-flex items-center gap-1 rounded-md border border-line bg-panel-2 px-1.5 py-0.5 text-[11px] font-medium text-muted">
                        <Clock aria-hidden className="h-3 w-3" />
                        <span className="tabular">{t.window}</span>
                      </span>
                    )}
                  </div>
                </div>
              </StaggerItem>
            );
          })}
        </Stagger>
      ) : (
        <Empty>No tips for this forecast.</Empty>
      )}

      {best.length > 0 && (
        <div className="border-t border-line pt-4">
          <Eyebrow className="mb-2 flex items-center gap-1.5">
            <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-lvl-green" />
            Greenest hours
          </Eyebrow>
          <ul className="flex flex-wrap gap-1.5">
            {best.map((h) => (
              <li
                key={h}
                className="tabular rounded-md border border-line bg-panel-2 px-1.5 py-0.5 text-[11px] font-medium text-muted"
              >
                {dayHourLabel(h)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
