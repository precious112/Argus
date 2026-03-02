-- TimescaleDB schema for Argus SaaS mode.
-- All tables include tenant_id for RLS-based multi-tenancy.

-- 1. system_metrics
CREATE TABLE IF NOT EXISTS system_metrics (
    timestamp   TIMESTAMPTZ NOT NULL,
    tenant_id   VARCHAR(36) NOT NULL DEFAULT 'default',
    metric_name VARCHAR(100) NOT NULL,
    value       DOUBLE PRECISION NOT NULL,
    labels      JSONB
);
SELECT create_hypertable('system_metrics', 'timestamp', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_sm_tenant_ts ON system_metrics(tenant_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_sm_tenant_metric ON system_metrics(tenant_id, metric_name, timestamp DESC);

-- 2. log_index
CREATE TABLE IF NOT EXISTS log_index (
    timestamp       TIMESTAMPTZ NOT NULL,
    tenant_id       VARCHAR(36) NOT NULL DEFAULT 'default',
    file_path       TEXT NOT NULL DEFAULT '',
    line_offset     INTEGER NOT NULL DEFAULT 0,
    severity        VARCHAR(20) NOT NULL DEFAULT '',
    message_preview TEXT NOT NULL DEFAULT '',
    source          VARCHAR(100) NOT NULL DEFAULT ''
);
SELECT create_hypertable('log_index', 'timestamp', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_li_tenant_ts ON log_index(tenant_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_li_tenant_sev ON log_index(tenant_id, severity, timestamp DESC);

-- 3. sdk_events
CREATE TABLE IF NOT EXISTS sdk_events (
    timestamp  TIMESTAMPTZ NOT NULL,
    tenant_id  VARCHAR(36) NOT NULL DEFAULT 'default',
    service    VARCHAR(255) NOT NULL DEFAULT '',
    event_type VARCHAR(100) NOT NULL DEFAULT '',
    data       JSONB
);
SELECT create_hypertable('sdk_events', 'timestamp', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_se_tenant_ts ON sdk_events(tenant_id, timestamp DESC, service, event_type);

-- 4. spans
CREATE TABLE IF NOT EXISTS spans (
    timestamp      TIMESTAMPTZ NOT NULL,
    tenant_id      VARCHAR(36) NOT NULL DEFAULT 'default',
    trace_id       VARCHAR(64) NOT NULL DEFAULT '',
    span_id        VARCHAR(64) NOT NULL DEFAULT '',
    parent_span_id VARCHAR(64),
    service        VARCHAR(255) NOT NULL DEFAULT '',
    name           VARCHAR(255) NOT NULL DEFAULT '',
    kind           VARCHAR(20) NOT NULL DEFAULT 'internal',
    duration_ms    DOUBLE PRECISION,
    status         VARCHAR(20) NOT NULL DEFAULT 'ok',
    error_type     VARCHAR(255),
    error_message  TEXT,
    data           JSONB
);
SELECT create_hypertable('spans', 'timestamp', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_sp_tenant_ts ON spans(tenant_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_sp_tenant_trace ON spans(tenant_id, trace_id);
CREATE INDEX IF NOT EXISTS idx_sp_tenant_svc ON spans(tenant_id, service, timestamp DESC);

-- 5. dependency_calls
CREATE TABLE IF NOT EXISTS dependency_calls (
    timestamp      TIMESTAMPTZ NOT NULL,
    tenant_id      VARCHAR(36) NOT NULL DEFAULT 'default',
    service        VARCHAR(255) NOT NULL DEFAULT '',
    dep_type       VARCHAR(50) NOT NULL DEFAULT '',
    target         VARCHAR(255) NOT NULL DEFAULT '',
    trace_id       VARCHAR(64),
    span_id        VARCHAR(64),
    parent_span_id VARCHAR(64),
    operation      VARCHAR(255) NOT NULL DEFAULT '',
    duration_ms    DOUBLE PRECISION,
    status         VARCHAR(20) NOT NULL DEFAULT 'ok',
    status_code    INTEGER,
    error_message  TEXT,
    data           JSONB
);
SELECT create_hypertable('dependency_calls', 'timestamp', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_dc_tenant_ts ON dependency_calls(tenant_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_dc_tenant_svc ON dependency_calls(tenant_id, service, dep_type, timestamp DESC);

-- 6. sdk_metrics
CREATE TABLE IF NOT EXISTS sdk_metrics (
    timestamp   TIMESTAMPTZ NOT NULL,
    tenant_id   VARCHAR(36) NOT NULL DEFAULT 'default',
    service     VARCHAR(255) NOT NULL DEFAULT '',
    metric_name VARCHAR(100) NOT NULL DEFAULT '',
    value       DOUBLE PRECISION NOT NULL,
    labels      JSONB
);
SELECT create_hypertable('sdk_metrics', 'timestamp', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_sdkm_tenant_ts ON sdk_metrics(tenant_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_sdkm_tenant_svc ON sdk_metrics(tenant_id, service, metric_name, timestamp DESC);

-- 7. deploy_events
CREATE TABLE IF NOT EXISTS deploy_events (
    timestamp        TIMESTAMPTZ NOT NULL,
    tenant_id        VARCHAR(36) NOT NULL DEFAULT 'default',
    service          VARCHAR(255) NOT NULL DEFAULT '',
    version          VARCHAR(100) NOT NULL DEFAULT '',
    git_sha          VARCHAR(64) NOT NULL DEFAULT '',
    environment      VARCHAR(50) NOT NULL DEFAULT '',
    previous_version VARCHAR(100) NOT NULL DEFAULT '',
    data             JSONB
);
SELECT create_hypertable('deploy_events', 'timestamp', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_de_tenant_ts ON deploy_events(tenant_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_de_tenant_svc ON deploy_events(tenant_id, service, timestamp DESC);

-- 8. metric_baselines (regular table, not hypertable)
CREATE TABLE IF NOT EXISTS metric_baselines (
    timestamp    TIMESTAMPTZ NOT NULL,
    tenant_id    VARCHAR(36) NOT NULL DEFAULT 'default',
    metric_name  VARCHAR(255) NOT NULL,
    mean         DOUBLE PRECISION NOT NULL DEFAULT 0,
    stddev       DOUBLE PRECISION NOT NULL DEFAULT 0,
    min_val      DOUBLE PRECISION NOT NULL DEFAULT 0,
    max_val      DOUBLE PRECISION NOT NULL DEFAULT 0,
    p50          DOUBLE PRECISION NOT NULL DEFAULT 0,
    p95          DOUBLE PRECISION NOT NULL DEFAULT 0,
    p99          DOUBLE PRECISION NOT NULL DEFAULT 0,
    sample_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_mb_tenant ON metric_baselines(tenant_id, metric_name);

-- RLS policies for all timeseries tables
DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOREACH tbl IN ARRAY ARRAY[
        'system_metrics', 'log_index', 'sdk_events', 'spans',
        'dependency_calls', 'sdk_metrics', 'deploy_events', 'metric_baselines'
    ] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', tbl);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', tbl);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I '
            'USING (tenant_id = current_setting(''app.current_tenant'', true)) '
            'WITH CHECK (tenant_id = current_setting(''app.current_tenant'', true))',
            tbl
        );
    END LOOP;
END $$;

-- Default retention policies (30 days)
SELECT add_retention_policy('system_metrics', INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_retention_policy('log_index', INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_retention_policy('sdk_events', INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_retention_policy('spans', INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_retention_policy('dependency_calls', INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_retention_policy('sdk_metrics', INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_retention_policy('deploy_events', INTERVAL '90 days', if_not_exists => TRUE);

-- Continuous aggregates
CREATE MATERIALIZED VIEW IF NOT EXISTS sdk_events_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', timestamp) AS bucket,
    tenant_id,
    service,
    event_type,
    COUNT(*) AS event_count
FROM sdk_events
GROUP BY bucket, tenant_id, service, event_type
WITH NO DATA;

SELECT add_continuous_aggregate_policy('sdk_events_hourly',
    start_offset => INTERVAL '3 hours',
    end_offset   => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE
);

CREATE MATERIALIZED VIEW IF NOT EXISTS spans_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', timestamp) AS bucket,
    tenant_id,
    service,
    name,
    COUNT(*) AS span_count,
    AVG(duration_ms) AS avg_duration,
    MAX(duration_ms) AS max_duration,
    COUNT(*) FILTER (WHERE status != 'ok') AS error_count
FROM spans
GROUP BY bucket, tenant_id, service, name
WITH NO DATA;

SELECT add_continuous_aggregate_policy('spans_hourly',
    start_offset => INTERVAL '3 hours',
    end_offset   => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE
);
