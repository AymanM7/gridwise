"""Write DataFrames as Parquet locally and upload them to the UC Volume landing zone."""
import io

import pandas as pd

from .config import Settings

_ws = None


def _workspace(s: Settings):
    global _ws
    if _ws is None:
        from databricks.sdk import WorkspaceClient
        _ws = WorkspaceClient(host=s.databricks_host, token=s.databricks_token)
    return _ws


def _parquet_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, coerce_timestamps="us", allow_truncated_timestamps=True)
    return buf.getvalue()


def land(df: pd.DataFrame, s: Settings, source: str, name: str, upload: bool = True) -> str:
    """Save to data/landing/<source>/<name>.parquet and (optionally) the Volume."""
    data = _parquet_bytes(df)
    local = s.local_landing / source / f"{name}.parquet"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(data)
    if not upload:
        return str(local)
    remote = f"{s.volume_root}/{source}/{name}.parquet"
    _workspace(s).files.upload(remote, io.BytesIO(data), overwrite=True)
    return remote


def run_job(s: Settings) -> None:
    """Trigger the Databricks Job and wait for it (used once Phase 4 sets DATABRICKS_JOB_ID)."""
    run = _workspace(s).jobs.run_now(job_id=int(s.job_id)).result()
    print(f"job run {run.run_id}: {run.state.result_state}")
