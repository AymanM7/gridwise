"""Tiger Data connection pool (psycopg 3)."""
from __future__ import annotations

import os

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import DATABASE_URL

pool: ConnectionPool | None = None


def open_pool() -> None:
    global pool
    if pool is None and DATABASE_URL:
        serverless = bool(os.getenv("VERCEL"))
        pool = ConnectionPool(DATABASE_URL, min_size=0 if serverless else 1, max_size=2 if serverless else 8,
                              open=False, timeout=15,
                              kwargs={"row_factory": dict_row, "autocommit": True, "connect_timeout": 10})
        pool.open(wait=False)


def close_pool() -> None:
    global pool
    if pool is not None:
        pool.close()
        pool = None


def fetch(sql: str, params=None) -> list[dict]:
    if pool is None:
        open_pool()  # serverless (Vercel) may not run the ASGI lifespan, so open lazily
    if pool is None:
        raise RuntimeError("database not configured (TIGER_DATABASE_URL)")
    with pool.connection() as conn:
        return conn.execute(sql, params).fetchall()


def fetch_one(sql: str, params=None) -> dict | None:
    rows = fetch(sql, params)
    return rows[0] if rows else None
