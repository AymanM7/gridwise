# Databricks notebook source
# MAGIC %md
# MAGIC # 00 · Setup (Phase 1.3)
# MAGIC Creates the Unity Catalog layout for GridWise:
# MAGIC - catalog `grid` (or the built-in `workspace` catalog if Free Edition won't let you create one)
# MAGIC - schemas `bronze`, `silver`, `gold`, `ml`
# MAGIC - volumes `bronze.landing` (worker uploads land here) and `bronze.checkpoints` (Auto Loader state)
# MAGIC
# MAGIC Run once. Safe to re-run.

# COMMAND ----------

dbutils.widgets.text("catalog", "grid")
catalog = dbutils.widgets.get("catalog")

# COMMAND ----------

try:
    spark.sql(f"CREATE CATALOG IF NOT EXISTS {catalog}")
    print(f"catalog `{catalog}` ready")
except Exception as e:
    raise RuntimeError(
        f"Could not create catalog `{catalog}`: {e}\n"
        "Set the `catalog` widget to `workspace` and re-run, then put "
        "GRIDWISE_CATALOG=workspace in your .env"
    )

for schema in ["bronze", "silver", "gold", "ml"]:
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}")

spark.sql(f"CREATE VOLUME IF NOT EXISTS {catalog}.bronze.landing COMMENT 'Raw parquet uploaded by the GridWise worker'")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {catalog}.bronze.checkpoints COMMENT 'Auto Loader schema + checkpoint state'")

# COMMAND ----------

display(spark.sql(f"SHOW SCHEMAS IN {catalog}"))
display(spark.sql(f"SHOW VOLUMES IN {catalog}.bronze"))
print(f"Landing path for the worker: /Volumes/{catalog}/bronze/landing")
