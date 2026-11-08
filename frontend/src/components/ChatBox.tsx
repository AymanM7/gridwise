"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { postChat } from "../lib/api";
import type { Forecast } from "../lib/types";
import { Badge, ErrorBox } from "./ui";

const EXAMPLES = [
  "I need 40 kWh in my car by 7 am. When should I charge?",
  "When should I run the laundry?",
  "Why is tomorrow evening red?",
];

interface Msg {
  q: string;
  a: string;
  offline: boolean;
  n: number;
}

export default function ChatBox({ forecast, onHighlight }: { forecast?: Forecast; onHighlight: (ts: string[]) => void }) {
  const [text, setText] = useState("");
  const [log, setLog] = useState<Msg[]>([]);
  const m = useMutation({
    mutationFn: (q: string) => postChat(q, forecast),
    onSuccess: (r, q) => {
      setLog((l) => [{ q, a: r.data.answer, offline: r.source !== "api", n: r.data.highlight_hours.length }, ...l].slice(0, 5));
      onHighlight(r.data.highlight_hours);
    },
  });

  function ask(q: string) {
    const v = q.trim();
    if (!v || m.isPending) return;
    setText("");
    m.mutate(v.slice(0, 500));
  }

  return (
    <div className="space-y-3">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          ask(text);
        }}
        className="flex gap-2"
      >
        <label htmlFor="chat-q" className="sr-only">
          Ask about the grid
        </label>
        <input
          id="chat-q"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Ask: when should I charge my EV?"
          maxLength={500}
          className="min-w-0 flex-1 rounded-xl border border-line bg-panel-2 px-3 py-2.5 text-sm placeholder:text-muted"
        />
        <button
          type="submit"
          disabled={m.isPending || !text.trim()}
          className="rounded-xl bg-sky-500 px-4 py-2.5 text-sm font-semibold text-black hover:bg-sky-400 disabled:opacity-50"
        >
          {m.isPending ? "…" : "Ask"}
        </button>
      </form>
      <div className="flex flex-wrap gap-2">
        {EXAMPLES.map((e) => (
          <button
            key={e}
            onClick={() => ask(e)}
            className="rounded-full border border-line px-3 py-1 text-xs text-muted hover:border-sky-400/50 hover:text-text"
          >
            {e}
          </button>
        ))}
      </div>
      {m.isPending && (
        <div role="status" className="animate-pulse text-sm text-muted">
          Thinking about the forecast…
        </div>
      )}
      {m.isError && <ErrorBox message={`Chat failed: ${(m.error as Error).message}`} />}
      <ul className="space-y-3" aria-live="polite">
        {log.map((x, i) => (
          <li key={i} className="space-y-1">
            <div className="text-xs text-muted">You: {x.q}</div>
            <div className="rounded-xl bg-panel-2 p-3 text-sm">
              {x.a}
              <div className="mt-2 flex flex-wrap gap-2">
                {x.offline && <Badge tone="warn">Offline answer (rules)</Badge>}
                {x.n > 0 && i === 0 && (
                  <button onClick={() => onHighlight([])} className="text-xs text-sky-300 underline">
                    Clear {x.n} highlighted hours
                  </button>
                )}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
