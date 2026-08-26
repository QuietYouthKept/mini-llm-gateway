from __future__ import annotations

SCHEMA_VERSION = 6

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version   INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS clients (
    client_id   TEXT PRIMARY KEY,
    api_key     TEXT NOT NULL,
    enabled     INTEGER NOT NULL DEFAULT 1,
    rate_limit_requests_per_minute INTEGER NOT NULL DEFAULT 60,
    budget_period    TEXT NOT NULL DEFAULT 'daily',
    budget_max_tokens INTEGER NOT NULL DEFAULT 100000,
    budget_max_cost_usd REAL NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS token_budget_usage (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id   TEXT NOT NULL REFERENCES clients(client_id),
    period      TEXT NOT NULL,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    cost_used_usd REAL NOT NULL DEFAULT 0,
    last_updated TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(client_id, period)
);

CREATE TABLE IF NOT EXISTS token_budget_reservations (
    reservation_id TEXT PRIMARY KEY,
    client_id      TEXT NOT NULL REFERENCES clients(client_id),
    period         TEXT NOT NULL,
    tokens_reserved INTEGER NOT NULL,
    cost_reserved_usd REAL NOT NULL DEFAULT 0,
    state          TEXT NOT NULL DEFAULT 'reserved'
                   CHECK (state IN ('reserved', 'settled', 'released')),
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at     TEXT NOT NULL,
    settled_at     TEXT,
    released_at    TEXT
);

CREATE TABLE IF NOT EXISTS request_logs (
    request_id   TEXT PRIMARY KEY,
    client_id    TEXT,
    model_profile TEXT,
    endpoint     TEXT,
    selected_provider TEXT,
    fallback_used INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL,
    status_code  INTEGER,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_input_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_output_tokens INTEGER NOT NULL DEFAULT 0,
    actual_input_tokens INTEGER,
    actual_output_tokens INTEGER,
    usage_source TEXT NOT NULL DEFAULT 'estimated',
    estimated_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd REAL NOT NULL DEFAULT 0,
    cost_saved_usd REAL NOT NULL DEFAULT 0,
    budget_before INTEGER,
    budget_after  INTEGER,
    duration_ms   INTEGER,
    error_code    TEXT,
    error_message TEXT,
    cache_hit     INTEGER NOT NULL DEFAULT 0,
    cache_key     TEXT,
    decision_trace TEXT,
    replay_payload TEXT,
    request_body TEXT,
    response_body TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS provider_attempts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id   TEXT NOT NULL REFERENCES request_logs(request_id),
    provider_id  TEXT NOT NULL,
    attempt_order INTEGER NOT NULL DEFAULT 0,
    retry_index  INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL,
    status_code  INTEGER,
    latency_ms    INTEGER,
    error_code    TEXT,
    error_message TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS config_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    detail     TEXT,
    checksum   TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_request_logs_client_id ON request_logs(client_id);
CREATE INDEX IF NOT EXISTS idx_request_logs_created_at ON request_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_provider_attempts_request_id ON provider_attempts(request_id);
CREATE INDEX IF NOT EXISTS idx_budget_reservations_client_period
ON token_budget_reservations(client_id, period);
CREATE INDEX IF NOT EXISTS idx_budget_reservations_expiry
ON token_budget_reservations(state, expires_at);
"""
