-- PostgreSQL production schema design. Not applied by the SQLite bootstrap.
-- Apply with a PostgreSQL migration runner in a controlled environment.

CREATE TABLE IF NOT EXISTS clients (
    client_id text PRIMARY KEY,
    api_key text NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    rate_limit_requests_per_minute integer NOT NULL DEFAULT 60,
    budget_period text NOT NULL DEFAULT 'daily',
    budget_max_tokens bigint NOT NULL DEFAULT 100000,
    budget_max_cost_usd numeric(18, 8) NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS token_budget_usage (
    client_id text NOT NULL REFERENCES clients(client_id),
    period text NOT NULL,
    tokens_used bigint NOT NULL DEFAULT 0 CHECK (tokens_used >= 0),
    cost_used_usd numeric(18, 8) NOT NULL DEFAULT 0 CHECK (cost_used_usd >= 0),
    last_updated timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (client_id, period)
);

CREATE TABLE IF NOT EXISTS token_budget_reservations (
    reservation_id text PRIMARY KEY,
    client_id text NOT NULL REFERENCES clients(client_id),
    period text NOT NULL,
    tokens_reserved bigint NOT NULL CHECK (tokens_reserved >= 0),
    cost_reserved_usd numeric(18, 8) NOT NULL DEFAULT 0 CHECK (cost_reserved_usd >= 0),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_budget_reservations_client_period
ON token_budget_reservations (client_id, period);

CREATE TABLE IF NOT EXISTS request_logs (
    request_id text PRIMARY KEY,
    client_id text,
    model_profile text,
    endpoint text,
    selected_provider text,
    fallback_used boolean NOT NULL DEFAULT false,
    status text NOT NULL,
    status_code integer,
    input_tokens bigint NOT NULL DEFAULT 0,
    output_tokens bigint NOT NULL DEFAULT 0,
    estimated_input_tokens bigint NOT NULL DEFAULT 0,
    estimated_output_tokens bigint NOT NULL DEFAULT 0,
    actual_input_tokens bigint,
    actual_output_tokens bigint,
    usage_source text NOT NULL DEFAULT 'estimated',
    estimated_tokens bigint NOT NULL DEFAULT 0,
    estimated_cost_usd numeric(18, 8) NOT NULL DEFAULT 0,
    cost_saved_usd numeric(18, 8) NOT NULL DEFAULT 0,
    budget_before bigint,
    budget_after bigint,
    duration_ms integer,
    error_code text,
    error_message text,
    cache_hit boolean NOT NULL DEFAULT false,
    cache_key text,
    decision_trace jsonb,
    replay_payload jsonb,
    request_body jsonb,
    response_body jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_request_logs_client_id ON request_logs (client_id);
CREATE INDEX IF NOT EXISTS idx_request_logs_created_at ON request_logs (created_at);

CREATE TABLE IF NOT EXISTS provider_attempts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    request_id text NOT NULL REFERENCES request_logs(request_id) ON DELETE CASCADE,
    provider_id text NOT NULL,
    attempt_order integer NOT NULL DEFAULT 0,
    retry_index integer NOT NULL DEFAULT 0,
    status text NOT NULL,
    status_code integer,
    latency_ms integer,
    error_code text,
    error_message text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_provider_attempts_request_id ON provider_attempts (request_id);

CREATE TABLE IF NOT EXISTS config_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_type text NOT NULL,
    detail text,
    checksum text,
    created_at timestamptz NOT NULL DEFAULT now()
);
