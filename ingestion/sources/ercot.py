"""ERCOT via gridstatus: live load, real-time prices, wind & solar actual + forecast.

gridstatus returns tz-aware Central times, so DST is already resolved; we still keep
the local ISO string (with offset) so Silver can show/verify the fall-back duplicate hour.
"""
import logging

import pandas as pd

from ..config import PRICE_HUBS
from .common import stamp, tidy_ercot

logging.getLogger("gridstatus").setLevel(logging.WARNING)

_client = None


def _ercot():
    global _client
    if _client is None:
        import gridstatus
        _client = gridstatus.Ercot()
    return _client


def load(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """5-minute system load (recent days)."""
    df = _ercot().get_load(start, end=end)
    df = tidy_ercot(df).rename(columns={"load": "load_mw"})
    return stamp(df, "ercot_load")


def prices(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """15-minute real-time settlement point prices for the hub average (recent days)."""
    df = _ercot().get_spp(start, end=end, market="REAL_TIME_15_MIN", locations=PRICE_HUBS)
    df = tidy_ercot(df).rename(columns={"spp": "price_usd_mwh"})
    return stamp(df, "ercot_rtm_spp")


def prices_year(year: int) -> pd.DataFrame:
    """Full-year historical RTM SPP archive (slow: ~100 s/year)."""
    df = _ercot().get_rtm_spp(year)
    df = df[df["Location"].isin(PRICE_HUBS)]
    df = tidy_ercot(df).rename(columns={"spp": "price_usd_mwh"})
    return stamp(df, "ercot_rtm_spp_archive")


def _renewable(kind: str) -> pd.DataFrame:
    e = _ercot()
    fn = e.get_wind_actual_and_forecast_hourly if kind == "wind" else e.get_solar_actual_and_forecast_hourly
    df = fn("latest")
    keep = [c for c in df.columns if c in ("Interval Start", "Interval End", "Publish Time")
            or c.endswith("SYSTEM WIDE")]
    df = tidy_ercot(df[keep])
    df = df.rename(columns={
        "gen_system_wide": "gen_mw",
        "stwpf_system_wide": "forecast_mw",   # wind short-term forecast
        "stppf_system_wide": "forecast_mw",   # solar short-term forecast
        "hsl_system_wide": "hsl_mw",
        "cop_hsl_system_wide": "cop_hsl_mw",
        "wgrpp_system_wide": "forecast_p80_mw",
        "pvgrpp_system_wide": "forecast_p80_mw",
    })
    return stamp(df, f"ercot_{kind}_hourly")


def wind_latest() -> pd.DataFrame:
    """Latest hourly wind report: 48 h actuals + 168 h forecast."""
    return _renewable("wind")


def solar_latest() -> pd.DataFrame:
    """Latest hourly solar report: 48 h actuals + 168 h forecast."""
    return _renewable("solar")
