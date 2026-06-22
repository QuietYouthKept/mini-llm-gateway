from __future__ import annotations

SCHEMA_VERSION = 1

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
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS token_budget_usage (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id   TEXT NOT NULL REFERENCES clients(client_id),
    period      TEXT NOT NULL,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    last_updated TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS request_logs (
    request_id   TEXT PRIMARY KEY,
    client_id    TEXT,
    model_profile TEXT,
    status       TEXT NOT NULL,
    status_code  INTEGER,
    request_body TEXT,
    response_body TEXT,
    budget_before INTEGER,
    budget_after  INTEGER,
    estimated_tokens INTEGER,
    duration_ms   INTEGER,
    error_code    TEXT,
    error_message TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS provider_attempts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id   TEXT NOT NULL REFERENCES request_logs(request_id),
    provider_id  TEXT NOT NULL,
    attempt_order INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL,
    status_code  INTEGER,
    latency_ms    INTEGER,
    error_message TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_request_logs_client_id ON request_logs(client_id);
CREATE INDEX IF NOT EXISTS idx_request_logs_created_at ON request_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_provider_attempts_request_id ON provider_attempts(request_id);
"""
