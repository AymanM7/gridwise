-- GridWise serving schema (Tiger Data: Postgres 18 + TimescaleDB 2.x)
-- Idempotent: safe to run on every sync. Statements are separated by ';' at end of line
-- and are executed one by one in autocommit mode (continuous aggregates cannot be
-- created inside a transaction block). Do not use $$ blocks in this file.

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ---------------------------------------------------------------- forecasts
-- One 48-row batch per run_ts (copied from grid.gold.forecasts). Sync keeps 7 days of batches.
CREATE TABLE IF NOT EXISTS forecasts (
    run_ts          timestamptz      NOT NULL,
    target_ts       timestamptz      NOT NULL,
    horizon_h       integer          NOT NULL,
    net_load_mw     double precision,          -- gold.net_load_used (what strain is based on)
    demand_mw       double precision,          -- gold.demand_p50
    band_low_mw     double precision,
    band_high_mw    double precision,
    net_load_p10    double precision,          -- Model A quantiles (kept for reference)
    net_load_p50    double precision,
    net_load_p90    double precision,
    strain_index    double precision,
    level           text,
    spike_prob      double precision,
    low_confidence  boolean,
    strain_source   text,
    band_source     text,
    wind_fcst_mw    double precision,
    solar_fcst_mw   double precision,
    local_month     integer,
    synced_at       timestamptz      NOT NULL DEFAULT now(),
    PRIMARY KEY (target_ts, run_ts)
);
SELECT create_hypertable('forecasts', by_range('target_ts', INTERVAL '7 days'), if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS forecasts_run_ts_idx ON forecasts (run_ts DESC, target_ts);
-- gold.created_at = when ml/05_predict wrote the batch. run_ts is the data anchor hour, which trails the wall clock
-- by ERCOT/EIA latency (~3 h), so /api/health measures forecast age from created_at.
ALTER TABLE forecasts ADD COLUMN IF NOT EXISTS created_at timestamptz;

-- ---------------------------------------------------------------- forecast_drivers
CREATE TABLE IF NOT EXISTS forecast_drivers (
    run_ts         timestamptz NOT NULL,
    target_ts      timestamptz NOT NULL,
    rank           integer     NOT NULL,
    feature        text        NOT NULL,
    label          text,
    value          double precision,
    shap_mw        double precision,
    direction      text,
    driver_source  text,
    synced_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_ts, target_ts, rank)
);
CREATE INDEX IF NOT EXISTS forecast_drivers_target_idx ON forecast_drivers (target_ts, run_ts DESC);

-- ---------------------------------------------------------------- daily_advice
CREATE TABLE IF NOT EXISTS daily_advice (
    date_local    date        PRIMARY KEY,
    run_ts        timestamptz,
    generated_by  text        NOT NULL DEFAULT 'gemini',   -- 'gemini' | 'rules'
    headline      text,
    tips          jsonb       NOT NULL DEFAULT '[]'::jsonb, -- [{icon, text, window}]
    best_hours    jsonb       NOT NULL DEFAULT '[]'::jsonb, -- [local_time]
    avoid_hours   jsonb       NOT NULL DEFAULT '[]'::jsonb, -- [local_time]
    why_red       jsonb       NOT NULL DEFAULT '{}'::jsonb, -- {target_ts: sentence}
    raw           jsonb,                                    -- the full gold row, for debugging
    synced_at     timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- Ripple scenarios
CREATE TABLE IF NOT EXISTS shift_scenarios (
    run_ts             timestamptz      NOT NULL,
    participation_pct  double precision NOT NULL,
    kwh_per_home       double precision NOT NULL,
    from_window        text             NOT NULL,   -- e.g. '16-20' (local hours, end exclusive)
    to_window          text             NOT NULL,   -- e.g. '22-02'
    red_hours_before   integer,
    red_hours_after    integer,
    peak_mw_before     double precision,
    peak_mw_after      double precision,
    peak_reduction_mw  double precision,
    spike_prob_before  double precision,             -- max over the 48 h
    spike_prob_after   double precision,
    peakers_avoided    double precision,
    synced_at          timestamptz      NOT NULL DEFAULT now(),
    PRIMARY KEY (run_ts, participation_pct, kwh_per_home, from_window, to_window)
);

CREATE TABLE IF NOT EXISTS shift_scenario_curves (
    run_ts             timestamptz      NOT NULL,
    participation_pct  double precision NOT NULL,
    kwh_per_home       double precision NOT NULL,
    from_window        text             NOT NULL,
    to_window          text             NOT NULL,
    target_ts          timestamptz      NOT NULL,
    before_mw          double precision,
    after_mw           double precision,
    level_before       text,
    level_after        text,
    spike_before       double precision,
    spike_after        double precision,
    PRIMARY KEY (run_ts, participation_pct, kwh_per_home, from_window, to_window, target_ts)
);

-- ---------------------------------------------------------------- report_card
CREATE TABLE IF NOT EXISTS report_card (
    date                date        NOT NULL,
    source              text        NOT NULL,        -- 'live' | 'backtest'
    mape                double precision,
    demand_mape         double precision,
    wmape               double precision,
    spike_recall        double precision,
    spike_precision     double precision,
    spike_hours_actual  integer,
    spike_hours_caught  integer,
    band_coverage       double precision,
    n_hours             integer,
    basis               text,
    synced_at           timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (date, source)
);

-- ---------------------------------------------------------------- strain_reference
-- Monthly net-load percentile breakpoints (gold.strain_reference): lets the API recompute
-- strain for what-if curves exactly like 05_predict.
CREATE TABLE IF NOT EXISTS strain_reference (
    month        integer          NOT NULL,
    pct          integer          NOT NULL,
    net_load_mw  double precision NOT NULL,
    synced_at    timestamptz      NOT NULL DEFAULT now(),
    PRIMARY KEY (month, pct)
);
ALTER TABLE strain_reference ADD COLUMN IF NOT EXISTS synced_at timestamptz NOT NULL DEFAULT now();

-- ---------------------------------------------------------------- actuals
CREATE TABLE IF NOT EXISTS actuals (
    ts             timestamptz      NOT NULL PRIMARY KEY,
    demand_mw      double precision,
    wind_mw        double precision,
    solar_mw       double precision,
    net_load_mw    double precision,
    price_usd_mwh  double precision,
    strain_index   double precision,
    level          text,
    is_spike       boolean,
    synced_at      timestamptz      NOT NULL DEFAULT now()
);
SELECT create_hypertable('actuals', by_range('ts', INTERVAL '30 days'), if_not_exists => TRUE);

-- Daily rollup in Texas local time (continuous aggregate)
CREATE MATERIALIZED VIEW IF NOT EXISTS actuals_daily
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(INTERVAL '1 day', ts, 'America/Chicago')        AS day,
    max(net_load_mw)                                            AS peak_net_load_mw,
    max(strain_index)                                           AS max_strain,
    avg(price_usd_mwh)                                          AS avg_price,
    max(price_usd_mwh)                                          AS max_price,
    sum(CASE WHEN is_spike THEN 1 ELSE 0 END)                   AS spike_hours,
    count(*)                                                    AS n_hours
FROM actuals
GROUP BY 1
WITH NO DATA;

SELECT add_continuous_aggregate_policy('actuals_daily',
    start_offset      => INTERVAL '10 days',
    end_offset        => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists     => TRUE);

-- ---------------------------------------------------------------- sync bookkeeping
CREATE TABLE IF NOT EXISTS sync_log (
    id          bigserial   PRIMARY KEY,
    synced_at   timestamptz NOT NULL DEFAULT now(),
    counts      jsonb       NOT NULL,
    notes       text
);
