import type {
  Advice,
  ChatAnswer,
  Drivers,
  Forecast,
  Health,
  History,
  ReportCard,
  SimParams,
  Simulation,
} from "./types";
import { estimateSimulation, type RefPoint } from "./simulate";
import { offlineChat } from "./offlineChat";

import forecastFx from "../../fixtures/forecast.json";
import driversFx from "../../fixtures/drivers.json";
import adviceFx from "../../fixtures/advice.json";
import historyFx from "../../fixtures/history.json";
import reportFx from "../../fixtures/report_card.json";
import healthFx from "../../fixtures/health.json";
import refFx from "../../fixtures/strain_reference.json";

// "/" (production behind Caddy) → same-origin relative calls ("/api/..."); unset → local dev API.
export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
export const USE_FIXTURES = process.env.NEXT_PUBLIC_USE_FIXTURES === "1";

/** Where a payload came from: the live API, fixtures mode, or a saved snapshot because the API failed. */
export type Source = "api" | "fixtures" | "snapshot";
export interface Sourced<T> {
  data: T;
  source: Source;
}

const fx = {
  forecast: forecastFx as unknown as Forecast,
  drivers: driversFx as unknown as Record<string, Drivers>,
  advice: adviceFx as unknown as Advice,
  history: historyFx as unknown as History,
  report: reportFx as unknown as ReportCard,
  health: healthFx as unknown as Health,
  ref: refFx as unknown as RefPoint[],
};

export class ApiError extends Error {
  constructor(
    message: string,
    public status?: number,
  ) {
    super(message);
  }
}

async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), 15000);
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      ...init,
      signal: ctrl.signal,
      headers: { Accept: "application/json", ...(init?.headers || {}) },
    });
    if (!res.ok) {
      let detail = "";
      try {
        const body = await res.json();
        detail = typeof body?.detail === "string" ? body.detail : "";
      } catch {
        /* ignore */
      }
      throw new ApiError(detail || `Request failed (${res.status})`, res.status);
    }
    return (await res.json()) as T;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    throw new ApiError(e instanceof Error && e.name === "AbortError" ? "Request timed out" : "API unreachable");
  } finally {
    clearTimeout(t);
  }
}

/** Live first; on a network/5xx failure fall back to the bundled snapshot so the page never goes blank. */
async function withSnapshot<T>(path: string, snapshot: T): Promise<Sourced<T>> {
  if (USE_FIXTURES) return { data: snapshot, source: "fixtures" };
  try {
    return { data: await getJson<T>(path), source: "api" };
  } catch (e) {
    if (e instanceof ApiError && e.status && e.status < 500) throw e;
    return { data: snapshot, source: "snapshot" };
  }
}

export function fetchHealth(): Promise<Sourced<Health>> {
  return withSnapshot("/api/health", fx.health);
}

export function fetchForecast(hours = 48): Promise<Sourced<Forecast>> {
  return withSnapshot(`/api/forecast?hours=${hours}`, fx.forecast);
}

export function fetchAdvice(): Promise<Sourced<Advice>> {
  return withSnapshot("/api/advice", fx.advice);
}

export function fetchHistory(days = 30): Promise<Sourced<History>> {
  return withSnapshot(`/api/history?days=${days}`, fx.history);
}

export function fetchReportCard(days = 7): Promise<Sourced<ReportCard>> {
  return withSnapshot(`/api/report-card?days=${days}`, fx.report);
}

function fixtureDrivers(ts: string): Drivers | null {
  const key = Object.keys(fx.drivers).find((k) => new Date(k).getTime() === new Date(ts).getTime());
  return key ? fx.drivers[key] : null;
}

/** Returns null when the snapshot has no drivers for this hour (fixtures carry 3 hours). */
export async function fetchDrivers(ts: string): Promise<Sourced<Drivers | null>> {
  if (USE_FIXTURES) return { data: fixtureDrivers(ts), source: "fixtures" };
  try {
    return { data: await getJson<Drivers>(`/api/forecast/drivers?ts=${encodeURIComponent(ts)}`), source: "api" };
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return { data: null, source: "api" };
    if (e instanceof ApiError && e.status && e.status < 500) throw e;
    return { data: fixtureDrivers(ts), source: "snapshot" };
  }
}

export async function fetchSimulation(p: SimParams, forecast?: Forecast): Promise<Sourced<Simulation>> {
  const offline = () => estimateSimulation(forecast ?? fx.forecast, fx.ref, p);
  if (USE_FIXTURES) return { data: offline(), source: "fixtures" };
  const qs = new URLSearchParams({ pct: String(p.pct), kwh: String(p.kwh), from: p.from, to: p.to });
  try {
    return { data: await getJson<Simulation>(`/api/simulate?${qs}`), source: "api" };
  } catch (e) {
    if (e instanceof ApiError && e.status && e.status < 500) throw e;
    return { data: offline(), source: "snapshot" };
  }
}

export async function postChat(question: string, forecast?: Forecast): Promise<Sourced<ChatAnswer>> {
  if (USE_FIXTURES) return { data: offlineChat(question, forecast ?? fx.forecast), source: "fixtures" };
  try {
    const data = await getJson<ChatAnswer>("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    return { data, source: "api" };
  } catch (e) {
    if (e instanceof ApiError && e.status && e.status < 500) throw e;
    return { data: offlineChat(question, forecast ?? fx.forecast), source: "snapshot" };
  }
}
