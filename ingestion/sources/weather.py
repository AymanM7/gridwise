"""Open-Meteo hourly weather (free, no key) for the four ERCOT load centers."""
from datetime import date

import pandas as pd
import requests

from ..config import CITIES
from .common import stamp

ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
FORECAST = "https://api.open-meteo.com/v1/forecast"
VARS = [
    "temperature_2m", "relative_humidity_2m", "apparent_temperature",
    "wind_speed_10m", "cloud_cover", "shortwave_radiation",
]


def _call(url: str, extra: dict) -> pd.DataFrame:
    names = list(CITIES)
    params = {
        "latitude": ",".join(str(CITIES[c]["lat"]) for c in names),
        "longitude": ",".join(str(CITIES[c]["lon"]) for c in names),
        "hourly": ",".join(VARS),
        "timezone": "UTC",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        **extra,
    }
    r = requests.get(url, params=params, timeout=120)
    r.raise_for_status()
    payload = r.json()
    payload = payload if isinstance(payload, list) else [payload]
    frames = []
    for city, block in zip(names, payload):
        df = pd.DataFrame(block["hourly"])
        df["city"] = city
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    out["time_utc"] = pd.to_datetime(out.pop("time"), utc=True)
    return out


def history(start: date, end: date) -> pd.DataFrame:
    df = _call(ARCHIVE, {"start_date": start.isoformat(), "end_date": end.isoformat()})
    return stamp(df, "openmeteo_archive")


def forecast(past_days: int = 3, forecast_days: int = 3) -> pd.DataFrame:
    df = _call(FORECAST, {"past_days": past_days, "forecast_days": forecast_days})
    return stamp(df, "openmeteo_forecast")
