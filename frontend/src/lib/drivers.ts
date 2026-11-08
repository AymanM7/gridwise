import type { Driver } from "./types";

export interface PlainDriver {
  icon: string;
  text: string;
  impact: string;
  raises: boolean;
}

function gwOf(v: number | null): string {
  return v == null ? "?" : `${(v / 1000).toFixed(1)} GW`;
}

function signedGw(mw: number | null): string {
  if (mw == null) return "";
  const s = mw >= 0 ? "+" : "−";
  return `${s}${Math.abs(mw / 1000).toFixed(1)} GW`;
}

/**
 * SHAP drivers come out of the pipeline with model-centric labels ("ERCOT wind forecast raises").
 * Map them to plain copy for a home user. Wind/solar are measured against their training mean,
 * so "raises" means "less than usual" (known UX issue noted in docs/PHASE2_CONTRACT.md).
 */
export function plainDriver(d: Driver): PlainDriver {
  const raises = d.direction === "raises";
  const impact = `${signedGw(d.mw)} net load`;
  switch (d.feature) {
    case "ercot_wind_forecast":
      return {
        icon: "🌬️",
        text: raises ? `Light wind: only ${gwOf(d.value)} expected` : `Strong wind: ${gwOf(d.value)} expected`,
        impact,
        raises,
      };
    case "ercot_solar_forecast":
      return {
        icon: "☀️",
        text: raises
          ? d.value != null && d.value > 50
            ? `Solar fading: ${gwOf(d.value)} left`
            : "No solar after dark"
          : `Plenty of solar: ${gwOf(d.value)}`,
        impact,
        raises,
      };
    case "recent_demand_level":
      return {
        icon: "📈",
        text: raises ? "Demand is running higher than the model expected today" : "Demand is running lower than expected today",
        impact,
        raises,
      };
    case "cdd":
      return {
        icon: "🌡️",
        text: raises ? `Heat: ${d.value?.toFixed(1)} cooling degrees → more AC` : "Mild temperatures → less AC than usual",
        impact,
        raises,
      };
    case "hdd":
      return {
        icon: "🥶",
        text: raises ? `Cold: ${d.value?.toFixed(1)} heating degrees → more heating` : "Mild temperatures → less heating than usual",
        impact,
        raises,
      };
    case "demand_lag_48h":
      return {
        icon: "📅",
        text: raises ? `Demand was high two days ago (${gwOf(d.value)})` : `Demand was lighter two days ago (${gwOf(d.value)})`,
        impact,
        raises,
      };
    default: {
      const label = d.label.replace(/\s*\(.*\)$/, "");
      return { icon: raises ? "⬆️" : "⬇️", text: `${label} ${raises ? "pushes load up" : "eases load"}`, impact, raises };
    }
  }
}
