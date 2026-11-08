"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ArrowUp, Clock, X, Zap } from "lucide-react";
import { postChat } from "../lib/api";
import type { Forecast } from "../lib/types";
import { AnimatePresence, EASE_OUT, motion } from "./motion";
import { ErrorBox } from "./ui";
import { stripEmoji } from "./insights/shared";

const EXAMPLES = [
  "I need 40 kWh in my car by 7 am. When should I charge?",
  "When should I run the laundry?",
  "Why is tomorrow evening red?",
];

interface Msg {
  id: number;
  q: string;
  a: string;
  offline: boolean;
  n: number;
}

function Avatar() {
  return (
    <span
      aria-hidden
      className="grid h-7 w-7 shrink-0 place-items-center rounded-lg border border-line-strong bg-panel-3 text-accent"
    >
      <Zap className="h-3.5 w-3.5" strokeWidth={2} />
    </span>
  );
}

function TypingDots() {
  return (
    <span className="flex items-center gap-1" aria-hidden>
      {[0, 1, 2].map((i) => (
        <motion.span
          key={i}
          className="h-1.5 w-1.5 rounded-full bg-muted"
          animate={{ opacity: [0.25, 1, 0.25] }}
          transition={{ duration: 1.1, repeat: Infinity, delay: i * 0.16, ease: "easeInOut" }}
        />
      ))}
    </span>
  );
}

const bubbleIn = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0 },
  transition: { duration: 0.35, ease: EASE_OUT },
};

export default function ChatBox({ forecast, onHighlight }: { forecast?: Forecast; onHighlight: (ts: string[]) => void }) {
  const [text, setText] = useState("");
  const [log, setLog] = useState<Msg[]>([]);
  const [pendingQ, setPendingQ] = useState<string | null>(null);
  const [highlightOn, setHighlightOn] = useState(false);
  const idRef = useRef(0);
  const scrollRef = useRef<HTMLDivElement>(null);

  const m = useMutation({
    mutationFn: (q: string) => postChat(q, forecast),
    onSuccess: (r, q) => {
      const n = r.data.highlight_hours.length;
      setLog((l) => [...l, { id: ++idRef.current, q, a: r.data.answer, offline: r.source !== "api", n }].slice(-5));
      setHighlightOn(n > 0);
      onHighlight(r.data.highlight_hours);
    },
    onSettled: () => setPendingQ(null),
  });

  // Keep the newest message in view inside the thread (never scrolls the page itself).
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [log.length, pendingQ]);

  function ask(q: string) {
    const v = q.trim();
    if (!v || m.isPending) return;
    setText("");
    setPendingQ(v.slice(0, 500));
    m.mutate(v.slice(0, 500));
  }

  function clearHighlight() {
    setHighlightOn(false);
    onHighlight([]);
  }

  const latest = log[log.length - 1];
  const hasThread = log.length > 0 || pendingQ;

  return (
    <div className="space-y-4">
      {!hasThread && (
        <div className="flex items-start gap-2.5">
          <Avatar />
          <div className="rounded-2xl rounded-tl-md border border-line bg-panel-2/70 px-3.5 py-2.5 text-sm leading-relaxed text-muted">
            Ask me about the next 48 hours: when to charge, when to run laundry, or why an hour is red.
          </div>
        </div>
      )}
      {hasThread && (
        <div
          ref={scrollRef}
          className="max-h-[440px] space-y-4 overflow-y-auto overscroll-contain pr-1 [scrollbar-width:thin]"
          aria-live="polite"
        >
          <AnimatePresence initial={false}>
            {log.map((x) => (
              <motion.div key={x.id} {...bubbleIn} className="space-y-3">
                <div className="flex justify-end">
                  <div className="max-w-[85%] rounded-2xl rounded-br-md border border-line-strong bg-panel-3 px-3.5 py-2 text-sm text-text">
                    <span className="sr-only">You: </span>
                    {x.q}
                  </div>
                </div>
                <div className="flex items-start gap-2.5">
                  <Avatar />
                  <div className="min-w-0 max-w-[85%] space-y-2">
                    <div className="rounded-2xl rounded-tl-md border border-line bg-panel-2/70 px-3.5 py-2.5 text-sm leading-relaxed text-text/90">
                      <span className="sr-only">GridWise: </span>
                      {stripEmoji(x.a)}
                    </div>
                    {x.offline && (
                      <p className="pl-1 text-[11px] text-muted">Offline answer, built from the forecast rules.</p>
                    )}
                  </div>
                </div>
              </motion.div>
            ))}
            {pendingQ && (
              <motion.div key="pending" {...bubbleIn} className="space-y-3">
                <div className="flex justify-end">
                  <div className="max-w-[85%] rounded-2xl rounded-br-md border border-line-strong bg-panel-3 px-3.5 py-2 text-sm text-text">
                    {pendingQ}
                  </div>
                </div>
                <div className="flex items-center gap-2.5" role="status">
                  <Avatar />
                  <div className="rounded-2xl rounded-tl-md border border-line bg-panel-2/70 px-3.5 py-3">
                    <TypingDots />
                    <span className="sr-only">GridWise is thinking about the forecast…</span>
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}

      {m.isError && <ErrorBox message={`Chat failed: ${(m.error as Error).message}`} />}

      <AnimatePresence initial={false}>
        {highlightOn && latest && latest.n > 0 && (
          <motion.div
            key={`hl-${latest.id}`}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.3, ease: EASE_OUT }}
          >
            <span className="inline-flex items-center gap-2 rounded-full border border-sky-300/30 bg-sky-300/10 py-1 pl-2.5 pr-1 text-xs text-sky-100">
              <Clock aria-hidden className="h-3.5 w-3.5 text-accent" />
              <span className="tabular">
                {latest.n} hour{latest.n === 1 ? "" : "s"} highlighted on the timeline
              </span>
              <button
                type="button"
                onClick={clearHighlight}
                className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium text-accent transition-colors hover:bg-sky-300/15"
              >
                <X aria-hidden className="h-3 w-3" />
                Clear
              </button>
            </span>
          </motion.div>
        )}
      </AnimatePresence>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          ask(text);
        }}
        className="group relative flex items-center rounded-2xl border border-line-strong bg-panel-2 shadow-[0_1px_0_0_rgba(255,255,255,0.04)_inset] transition-colors focus-within:border-sky-300/50"
      >
        <label htmlFor="chat-q" className="sr-only">
          Ask about the grid
        </label>
        <input
          id="chat-q"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Ask GridWise: when should I charge my EV?"
          maxLength={500}
          autoComplete="off"
          className="min-w-0 flex-1 bg-transparent py-3.5 pl-4 pr-2 text-sm text-text placeholder:text-muted focus:outline-none focus-visible:outline-none"
        />
        <button
          type="submit"
          aria-label="Send question"
          disabled={m.isPending || !text.trim()}
          className="mr-2 grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-accent text-black transition-[opacity,transform,background-color] duration-200 hover:bg-sky-200 active:scale-95 disabled:bg-panel-3 disabled:text-faint"
        >
          <ArrowUp className="h-4 w-4" strokeWidth={2.25} />
        </button>
      </form>

      <motion.ul
        className="flex flex-wrap gap-2"
        aria-label="Suggested questions"
        initial="hidden"
        whileInView="show"
        viewport={{ once: true, amount: 0 }}
        variants={{ hidden: {}, show: { transition: { staggerChildren: 0.06, delayChildren: 0.1 } } }}
      >
        {EXAMPLES.map((e) => (
          <motion.li
            key={e}
            variants={{
              hidden: { opacity: 0, y: 6 },
              show: { opacity: 1, y: 0, transition: { duration: 0.4, ease: EASE_OUT } },
            }}
          >
            <button
              type="button"
              onClick={() => ask(e)}
              disabled={m.isPending}
              className="rounded-full border border-line bg-panel-2/40 px-3 py-1.5 text-left text-xs text-muted transition-[color,border-color,transform] duration-200 hover:-translate-y-px hover:border-line-strong hover:text-text disabled:opacity-50 motion-reduce:hover:translate-y-0"
            >
              {e}
            </button>
          </motion.li>
        ))}
      </motion.ul>
    </div>
  );
}
