"use client";

import { useEffect, useState } from "react";
import { Zap } from "lucide-react";
import { motion } from "../motion";

export interface NavItem {
  id: string;
  label: string;
}

/** Sticky brand bar with anchor chips; the active chip follows the section in view. */
export default function TopBar({ items }: { items: NavItem[] }) {
  const [active, setActive] = useState<string | null>(null);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const els = items.map((i) => document.getElementById(i.id)).filter((e): e is HTMLElement => !!e);
    if (!els.length || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      (entries) => {
        const vis = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (vis[0]) setActive(vis[0].target.id);
      },
      { rootMargin: "-30% 0px -60% 0px" },
    );
    els.forEach((e) => io.observe(e));
    return () => io.disconnect();
  }, [items]);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <div
      className={`sticky top-0 z-40 border-b transition-colors duration-300 ${
        scrolled ? "border-line bg-bg/75 backdrop-blur-xl" : "border-transparent bg-transparent"
      }`}
    >
      <div className="mx-auto flex h-14 max-w-7xl items-center gap-4 px-4 sm:px-6">
        <a href="#top" className="flex shrink-0 items-center gap-2.5 rounded-lg" aria-label="GridWise, back to top">
          <span className="relative grid h-7 w-7 place-items-center rounded-lg border border-white/10 bg-gradient-to-b from-panel-3 to-panel shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]">
            <Zap className="h-3.5 w-3.5 text-accent" strokeWidth={2.5} aria-hidden />
          </span>
          <span className="text-[15px] font-semibold tracking-tight text-text">GridWise</span>
          <span className="hidden rounded-md border border-line px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-[0.12em] text-muted md:inline">
            ERCOT · Texas
          </span>
        </a>

        <nav aria-label="Sections" className="-mr-4 ml-auto min-w-0 overflow-x-auto pr-4 [scrollbar-width:none] sm:mr-0 sm:pr-0">
          <ul className="flex items-center gap-0.5">
            {items.map((it) => {
              const on = active === it.id;
              return (
                <li key={it.id} className="relative">
                  <a
                    href={`#${it.id}`}
                    aria-current={on ? "true" : undefined}
                    className={`relative block whitespace-nowrap rounded-full px-3 py-1.5 text-[13px] font-medium transition-colors ${
                      on ? "text-text" : "text-muted hover:text-text"
                    }`}
                  >
                    {on && (
                      <motion.span
                        layoutId="nav-pill"
                        className="absolute inset-0 rounded-full border border-line-strong bg-white/[0.06]"
                        transition={{ type: "spring", stiffness: 420, damping: 36 }}
                      />
                    )}
                    <span className="relative">{it.label}</span>
                  </a>
                </li>
              );
            })}
          </ul>
        </nav>
      </div>
    </div>
  );
}
