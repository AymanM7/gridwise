"""Run SQL on the Databricks SQL warehouse and print the result as a table.

    python -m tools.sql "SELECT count(*) FROM grid.silver.grid_hourly"
"""
import sys
import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

from ingestion.config import get_settings
import os


def query(sql: str):
    s = get_settings()
    w = WorkspaceClient(host=s.databricks_host, token=s.databricks_token)
    wid = os.getenv("DATABRICKS_WAREHOUSE_ID") or next(iter(w.warehouses.list())).id
    r = w.statement_execution.execute_statement(statement=sql, warehouse_id=wid, wait_timeout="50s")
    while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(3)
        r = w.statement_execution.get_statement(r.statement_id)
    if r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"{r.status.state}: {r.status.error.message if r.status.error else ''}")
    cols = [c.name for c in r.manifest.schema.columns]
    rows = (r.result.data_array or []) if r.result else []
    return cols, rows


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cols, rows = query(" ".join(sys.argv[1:]))
    widths = [max(len(str(c)), *(len(str(x[i])) for x in rows)) if rows else len(c) for i, c in enumerate(cols)]
    print(" | ".join(c.ljust(w) for c, w in zip(cols, widths)))
    print("-+-".join("-" * w for w in widths))
    for row in rows[:200]:
        print(" | ".join(str(v).ljust(w) for v, w in zip(row, widths)))
    print(f"({len(rows)} rows)")


if __name__ == "__main__":
    main()
