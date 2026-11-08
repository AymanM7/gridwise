import { Zap } from "lucide-react";

const link = "text-text/80 underline decoration-white/20 underline-offset-4 transition-colors hover:text-text hover:decoration-white/60";

export default function Footer() {
  return (
    <footer className="mt-8 border-t border-line pt-8 text-xs leading-relaxed text-muted">
      <div className="grid gap-6 md:grid-cols-[auto_1fr_1fr] md:gap-10">
        <div className="flex items-center gap-2 self-start">
          <span className="grid h-6 w-6 place-items-center rounded-md border border-white/10 bg-panel-2">
            <Zap className="h-3 w-3 text-accent" strokeWidth={2.5} aria-hidden />
          </span>
          <span className="text-sm font-semibold tracking-tight text-text">GridWise</span>
        </div>
        <p>
          <span className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-[#8b929e]">Data</span>
          <a className={link} href="https://www.ercot.com/" target="_blank" rel="noreferrer">
            ERCOT
          </a>{" "}
          (load, wind/solar forecasts, real-time prices),{" "}
          <a className={link} href="https://www.eia.gov/opendata/" target="_blank" rel="noreferrer">
            U.S. EIA
          </a>{" "}
          (hourly grid data) and{" "}
          <a className={link} href="https://open-meteo.com/" target="_blank" rel="noreferrer">
            Open-Meteo
          </a>{" "}
          (weather). Forecasts by GridWise models on Databricks; plain-language advice by Google Gemini.
        </p>
        <p>
          <span className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-[#8b929e]">Disclaimer</span>
          GridWise is an independent student project (TAMUhack 26). It is{" "}
          <span className="font-medium text-text">not affiliated with or endorsed by ERCOT</span>, and its forecasts are estimates,
          not official grid conditions or emergency alerts. For official notices see ercot.com.
        </p>
      </div>
    </footer>
  );
}
