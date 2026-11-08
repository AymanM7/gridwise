import re

import pandas as pd


def snake(name: str) -> str:
    return re.sub(r"[^0-9a-zA-Z]+", "_", str(name)).strip("_").lower()


def tidy_ercot(df: pd.DataFrame) -> pd.DataFrame:
    """Snake-case columns; keep the original local timestamp (with its UTC offset,
    so DST duplicates stay distinguishable) and add UTC versions."""
    df = df.copy()
    df.columns = [snake(c) for c in df.columns]
    for col in ("interval_start", "interval_end", "time", "publish_time"):
        if col in df.columns and pd.api.types.is_datetime64tz_dtype(df[col]):
            if col == "interval_start":
                df["interval_start_local"] = df[col].map(lambda t: t.isoformat())
            df[f"{col}_utc"] = df[col].dt.tz_convert("UTC")
            df = df.drop(columns=col)
    return df


def stamp(df: pd.DataFrame, source: str) -> pd.DataFrame:
    df = df.copy()
    df["_source"] = source
    df["_fetched_at_utc"] = pd.Timestamp.now(tz="UTC")
    return df
