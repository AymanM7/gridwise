export default function Footer() {
  return (
    <footer className="space-y-2 border-t border-line pt-6 text-xs text-muted">
      <p>
        Data: <a className="underline hover:text-text" href="https://www.ercot.com/" target="_blank" rel="noreferrer">ERCOT</a> (load, wind/solar
        forecasts, real-time prices), <a className="underline hover:text-text" href="https://www.eia.gov/opendata/" target="_blank" rel="noreferrer">U.S. EIA</a>{" "}
        (hourly grid data) and <a className="underline hover:text-text" href="https://open-meteo.com/" target="_blank" rel="noreferrer">Open-Meteo</a> (weather).
        Forecasts by GridWise models on Databricks; plain-language advice by Google Gemini.
      </p>
      <p>
        GridWise is an independent student project (TAMUhack 26). It is <b className="text-text">not affiliated with or endorsed by ERCOT</b>, and its
        forecasts are estimates, not official grid conditions or emergency alerts. For official notices see ercot.com.
      </p>
    </footer>
  );
}
