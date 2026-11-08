// Rule-based chat used only in fixtures mode (or when POST /api/chat is unreachable).
// Grounded in the same forecast the page shows; the live API asks Gemini instead.
import type { ChatAnswer, Forecast, ForecastHour } from "./types";
import { dayHourLabel, hourLabel, localHour, pct } from "./format";

function bestRun(hours: ForecastHour[], len: number, filter: (h: ForecastHour) => boolean): ForecastHour[] {
  let best: ForecastHour[] = [];
  let bestScore = Infinity;
  for (let i = 0; i + len <= hours.length; i++) {
    const w = hours.slice(i, i + len);
    if (!w.every(filter)) continue;
    const score = w.reduce((s, h) => s + h.strain_index + (h.spike_prob ?? 0) * 100, 0);
    if (score < bestScore) {
      bestScore = score;
      best = w;
    }
  }
  return best;
}

function describe(w: ForecastHour[]): string {
  const end = new Date(new Date(w[w.length - 1].target_ts).getTime() + 3600_000).toISOString();
  const maxSpike = Math.max(...w.map((h) => h.spike_prob ?? 0));
  const levels = new Set(w.map((h) => h.level));
  const lvl = levels.has("red") ? "includes red hours" : levels.has("yellow") ? "is green to yellow" : "is green";
  return `${dayHourLabel(w[0].target_ts)} – ${hourLabel(end)}: that window ${lvl} with at most ${pct(maxSpike)} spike risk`;
}

export function offlineChat(question: string, fc: Forecast): ChatAnswer {
  const q = question.toLowerCase();
  const hours = fc.hours;
  const energyWords = /(charge|ev|car|laundry|wash|dry|dish|pool|pump|ac|thermostat|cool|heat|power|energy|grid|price|spike|red|when|hour|bill|kwh|oven|cook)/;
  if (!energyWords.test(q)) {
    return {
      answer:
        "I can only help with the Texas grid forecast and when to run appliances. Try: \"When should I charge my EV tonight?\" or \"Why is 5 pm red?\"",
      highlight_hours: [],
    };
  }
  if (/(why|red|spike|price)/.test(q)) {
    const reds = hours.filter((h) => h.level === "red");
    const top = [...hours].sort((a, b) => (b.spike_prob ?? 0) - (a.spike_prob ?? 0))[0];
    return {
      answer: reds.length
        ? `${reds.length} of the next 48 hours are red. The riskiest hour is ${dayHourLabel(top.target_ts)} with a ${pct(top.spike_prob)} chance of a price spike: light wind and fading solar leave gas plants to cover the evening peak. Tap a red bar to see the drivers.`
        : "No red hours in the next 48 hours. The grid looks comfortable.",
      highlight_hours: reds.length ? reds.map((h) => h.target_ts) : [],
    };
  }
  let len = 3;
  let filter = (h: ForecastHour) => h.level !== "red";
  if (/(charge|ev|car)/.test(q)) {
    len = 4;
    filter = (h) => h.level !== "red" && (localHour(h.target_ts) >= 22 || localHour(h.target_ts) < 7);
  } else if (/(pool|pump)/.test(q)) {
    len = 4;
    filter = (h) => h.level !== "red" && localHour(h.target_ts) >= 9 && localHour(h.target_ts) < 16;
  } else if (/(laundry|wash|dry|dish)/.test(q)) {
    len = 2;
  }
  let w = bestRun(hours, len, filter);
  if (!w.length) w = bestRun(hours, len, () => true);
  if (!w.length) return { answer: "I could not find a good window in the current forecast.", highlight_hours: [] };
  return {
    answer: `Best bet: ${describe(w)}. Those hours are highlighted on the timeline.`,
    highlight_hours: w.map((h) => h.target_ts),
  };
}
