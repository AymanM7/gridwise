# Databricks notebook source
# MAGIC %md
# MAGIC # 00 · Connectivity check (Phase 1.4)
# MAGIC Free Edition only allows outbound traffic to a short, unpublished list of trusted domains.
# MAGIC This tells us which parts of the pipeline can run **inside** Databricks and which need the worker.
# MAGIC
# MAGIC | If this is reachable… | …then |
# MAGIC |---|---|
# MAGIC | ercot.com / api.eia.gov / open-meteo | ingestion *could* run in a notebook (worker still works either way) |
# MAGIC | generativelanguage.googleapis.com | Gemini can be called from a notebook task |
# MAGIC | your Tiger Data host | `sync_to_tiger` can run in the Databricks Job |

# COMMAND ----------

dbutils.widgets.text("tiger_host", "")  # e.g. abc123.tsdb.cloud.timescale.com (optional)
dbutils.widgets.text("tiger_port", "5432")

import socket, time
import requests

targets = {
    "pypi.org (expected OK)": "https://pypi.org/simple/gridstatus/",
    "ERCOT": "https://www.ercot.com/",
    "EIA API": "https://api.eia.gov/v2/",
    "Open-Meteo forecast": "https://api.open-meteo.com/v1/forecast?latitude=29.76&longitude=-95.37&hourly=temperature_2m",
    "Open-Meteo archive": "https://archive-api.open-meteo.com/v1/archive?latitude=29.76&longitude=-95.37&start_date=2025-07-01&end_date=2025-07-01&hourly=temperature_2m",
    "Gemini API": "https://generativelanguage.googleapis.com/",
}

rows = []
for name, url in targets.items():
    t = time.time()
    try:
        r = requests.get(url, timeout=10)
        rows.append((name, "REACHABLE", r.status_code, round(time.time() - t, 2)))
    except Exception as e:
        rows.append((name, "BLOCKED", type(e).__name__, round(time.time() - t, 2)))

tiger = dbutils.widgets.get("tiger_host").strip()
if tiger:
    try:
        socket.create_connection((tiger, int(dbutils.widgets.get("tiger_port"))), timeout=10).close()
        rows.append(("Tiger Data", "REACHABLE", "tcp", 0))
    except Exception as e:
        rows.append(("Tiger Data", "BLOCKED", type(e).__name__, 0))

display(spark.createDataFrame([(a, b, str(c), float(d)) for a, b, c, d in rows],
                              "target string, status string, detail string, seconds double"))

# COMMAND ----------

import json
dbutils.notebook.exit(json.dumps([{"target": a, "status": b, "detail": str(c)} for a, b, c, _ in rows]))
