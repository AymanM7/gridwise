"use client";

/**
 * Shared animation primitives (motion v12, `motion/react`).
 * Every primitive respects prefers-reduced-motion via MotionConfig in providers.tsx.
 * Keep motion purposeful: entrance once, number tweens, layout shifts. No looping decoration.
 */
import {
  animate,
  motion,
  useInView,
  useMotionValue,
  useReducedMotion,
  useTransform,
  type HTMLMotionProps,
} from "motion/react";
import { useEffect, useRef, type ReactNode } from "react";

export const EASE_OUT = [0.22, 1, 0.36, 1] as const;
export const SPRING = { type: "spring", stiffness: 380, damping: 32, mass: 0.8 } as const;

/** Fade + 12px rise when scrolled into view (once). */
export function Reveal({
  children,
  delay = 0,
  y = 12,
  className,
  ...rest
}: { children: ReactNode; delay?: number; y?: number; className?: string } & Omit<HTMLMotionProps<"div">, "children">) {
  return (
    <motion.div
      initial={{ opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0 }}
      transition={{ duration: 0.55, ease: EASE_OUT, delay }}
      className={className}
      {...rest}
    >
      {children}
    </motion.div>
  );
}

/** Parent for staggered children: wrap items in <StaggerItem>. */
export function Stagger({
  children,
  className,
  stagger = 0.05,
  delay = 0,
  as = "div",
}: {
  children: ReactNode;
  className?: string;
  stagger?: number;
  delay?: number;
  as?: "div" | "ul" | "ol";
}) {
  const M = as === "ul" ? motion.ul : as === "ol" ? motion.ol : motion.div;
  return (
    <M
      className={className}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true, amount: 0 }}
      variants={{ hidden: {}, show: { transition: { staggerChildren: stagger, delayChildren: delay } } }}
    >
      {children}
    </M>
  );
}

export function StaggerItem({
  children,
  className,
  as = "div",
}: {
  children: ReactNode;
  className?: string;
  as?: "div" | "li";
}) {
  const M = as === "li" ? motion.li : motion.div;
  return (
    <M
      className={className}
      variants={{
        hidden: { opacity: 0, y: 8 },
        show: { opacity: 1, y: 0, transition: { duration: 0.45, ease: EASE_OUT } },
      }}
    >
      {children}
    </M>
  );
}

/**
 * Number that tweens from its previous value (or 0 on first view) to `value`.
 * format: how to render the number, e.g. (n) => `${n.toFixed(1)} GW`.
 */
export function AnimatedNumber({
  value,
  format = (n) => Math.round(n).toString(),
  duration = 0.9,
  className,
}: {
  value: number;
  format?: (n: number) => string;
  duration?: number;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true });
  const mv = useMotionValue(0);
  const text = useTransform(mv, (n) => format(n));
  const reduce = useReducedMotion();

  useEffect(() => {
    if (!inView) return;
    if (reduce) {
      mv.set(value); // reduced motion: jump straight to the value
      return;
    }
    const c = animate(mv, value, { duration, ease: EASE_OUT });
    return () => c.stop();
  }, [inView, value, duration, mv, reduce]);

  return (
    <motion.span ref={ref} className={`tabular ${className ?? ""}`}>
      {text}
    </motion.span>
  );
}

/** Small live indicator dot with a soft pulse ring. `color` is any CSS color. */
export function PulseDot({ color = "var(--green)", className = "" }: { color?: string; className?: string }) {
  return (
    <span
      aria-hidden
      className={`inline-block h-2 w-2 rounded-full animate-pulse-dot ${className}`}
      style={{ background: color, color }}
    />
  );
}

export { motion, AnimatePresence, LayoutGroup } from "motion/react";
