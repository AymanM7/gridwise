# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Bronze (Phase 1.7)
# MAGIC Incrementally loads the parquet files the worker uploaded to
# MAGIC `/Volumes/<catalog>/bronze/landing/<source>/` into Delta tables `<catalog>.bronze.<source>`.
# MAGIC
# MAGIC Uses **Auto Loader** with `availableNow`, so each run only picks up files it hasn't seen.
# MAGIC Rows are stored as-is, plus `_ingested_at` and `_source_file` for lineage.

# COMMAND ----------

dbutils.widgets.text("catalog", "grid")
catalog = dbutils.widgets.get("catalog")

LANDING = f"/Volumes/{catalog}/bronze/landing"
CKPT = f"/Volumes/{catalog}/bronze/checkpoints"
SOURCES = [
    "eia_hourly",        # history + recent: demand, demand forecast, wind, solar (hourly, UTC)
    "ercot_load",        # live 5-min load
    "ercot_prices",      # RT 15-min hub-average price (archive + live)
    "ercot_wind",        # hourly wind actual + 7-day forecast
    "ercot_solar",       # hourly solar actual + 7-day forecast
    "weather_hist",      # Open-Meteo archive, 4 cities
    "weather_forecast",  # Open-Meteo forecast (+3 past days), 4 cities
]

# COMMAND ----------

from pyspark.sql import functions as F


def has_files(path: str) -> bool:
    try:
        return len(dbutils.fs.ls(path)) > 0
    except Exception:
        return False


results = []
for src in SOURCES:
    path = f"{LANDING}/{src}"
    if not has_files(path):
        results.append((src, "skipped (no files yet)", None))
        continue
    q = (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "parquet")
        .option("cloudFiles.schemaLocation", f"{CKPT}/{src}/schema")
        .option("cloudFiles.schemaEvolutionMode", "rescue")
        .load(path)
        .withColumn("_ingested_at", F.current_timestamp())
        .withColumn("_source_file", F.col("_metadata.file_path"))
        .writeStream
        .option("checkpointLocation", f"{CKPT}/{src}/checkpoint")
        .option("mergeSchema", "true")
        .trigger(availableNow=True)
        .toTable(f"{catalog}.bronze.{src}")
    )
    q.awaitTermination()
    n = spark.table(f"{catalog}.bronze.{src}").count()
    results.append((src, "ok", n))

display(spark.createDataFrame(results, "source string, status string, total_rows long"))

# COMMAND ----------

# MAGIC %md ### Checkpoint 1: Bronze tables are queryable

# COMMAND ----------

display(spark.sql(f"""
  SELECT 'eia_hourly' AS tbl, min(interval_start_utc) AS first_ts, max(interval_start_utc) AS last_ts, count(*) AS n FROM {catalog}.bronze.eia_hourly
  UNION ALL
  SELECT 'ercot_prices', min(interval_start_utc), max(interval_start_utc), count(*) FROM {catalog}.bronze.ercot_prices
  UNION ALL
  SELECT 'weather_hist', min(time_utc), max(time_utc), count(*) FROM {catalog}.bronze.weather_hist
"""))
