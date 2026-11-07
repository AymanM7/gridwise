import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# Main ERCOT load centers. Weights ~ metro population (millions), used for a
# population-weighted Texas temperature in Silver.
CITIES = {
    "houston":     {"lat": 29.7604, "lon": -95.3698, "weight": 7.5},
    "dfw":         {"lat": 32.7767, "lon": -96.7970, "weight": 8.1},
    "austin":      {"lat": 30.2672, "lon": -97.7431, "weight": 2.5},
    "san_antonio": {"lat": 29.4241, "lon": -98.4936, "weight": 2.7},
}

# ERCOT hub used as the "system price" (hub average of the 4 trading hubs).
PRICE_HUBS = ["HB_HUBAVG"]


@dataclass(frozen=True)
class Settings:
    databricks_host: str
    databricks_token: str
    catalog: str
    job_id: str
    eia_api_key: str
    local_landing: Path

    @property
    def volume_root(self) -> str:
        return f"/Volumes/{self.catalog}/bronze/landing"

    @property
    def has_databricks(self) -> bool:
        return bool(self.databricks_host and self.databricks_token)


def get_settings() -> Settings:
    return Settings(
        databricks_host=os.getenv("DATABRICKS_HOST", "").rstrip("/"),
        databricks_token=os.getenv("DATABRICKS_TOKEN", ""),
        catalog=os.getenv("GRIDWISE_CATALOG", "grid"),
        job_id=os.getenv("DATABRICKS_JOB_ID", ""),
        eia_api_key=os.getenv("EIA_API_KEY") or "DEMO_KEY",
        local_landing=ROOT / "data" / "landing",
    )
