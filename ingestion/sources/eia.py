"""EIA-930 hourly ERCOT demand, wind and solar (multi-year history).

ERCOT's own MIS only keeps a few days of wind/solar reports, so EIA-930 is the
history source. EIA hourly periods are UTC and *hour-ending*; we convert to
interval_start_utc = period - 1h. (Phase 2 cross-checks this against ERCOT live load.)
Free key: https://www.eia.gov/opendata/register.php
"""
from datetime import date

import pandas as pd
import requests

from .common import stamp

BASE = "https://api.eia.gov/v2/electricity/rto"
PAGE = 5000


def _fetch(route: str, facets: dict, start: str, end: str, key: str) -> pd.DataFrame:
    rows, offset = [], 0
    while True:
        params = {
            "api_key": key, "frequency": "hourly", "data[0]": "value",
            "start": start, "end": end, "offset": offset, "length": PAGE,
            "sort[0][column]": "period", "sort[0][direction]": "asc",
        }
        for k, vals in facets.items():
            params[f"facets[{k}][]"] = vals
        r = requests.get(f"{BASE}/{route}/data/", params=params, timeout=120)
        r.raise_for_status()
        data = r.json()["response"]["data"]
        rows.extend(data)
        if len(data) < PAGE:
            return pd.DataFrame(rows)
        offset += PAGE


def fetch(start: date, end: date, key: str) -> pd.DataFrame:
    s, e = start.strftime("%Y-%m-%dT00"), end.strftime("%Y-%m-%dT23")
    dem = _fetch("region-data", {"respondent": ["ERCO"], "type": ["D", "DF"]}, s, e, key)
    fuel = _fetch("fuel-type-data", {"respondent": ["ERCO"], "fueltype": ["WND", "SUN"]}, s, e, key)
    if dem.empty and fuel.empty:
        return pd.DataFrame()
    dem["series"] = dem["type"].map({"D": "demand_mw", "DF": "demand_forecast_mw"})
    fuel["series"] = fuel["fueltype"].map({"WND": "wind_mw", "SUN": "solar_mw"})
    long = pd.concat([dem[["period", "series", "value"]], fuel[["period", "series", "value"]]])
    long["value"] = pd.to_numeric(long["value"], errors="coerce")
    wide = long.pivot_table(index="period", columns="series", values="value", aggfunc="last").reset_index()
    wide.columns.name = None
    wide["interval_end_utc"] = pd.to_datetime(wide["period"], format="%Y-%m-%dT%H", utc=True)
    wide["interval_start_utc"] = wide["interval_end_utc"] - pd.Timedelta(hours=1)
    wide = wide.drop(columns="period")
    for col in ("demand_mw", "demand_forecast_mw", "wind_mw", "solar_mw"):
        if col not in wide:
            wide[col] = pd.NA
    return stamp(wide, "eia930")
