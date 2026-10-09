-- Atomic terminal receipt for streaming budget settlement and its audit record.
CREATE TABLE IF NOT EXISTS stream_finalizations (
    reservation_id text PRIMARY KEY REFERENCES token_budget_reservations(reservation_id),
    request_id text NOT NULL UNIQUE REFERENCES request_logs(request_id),
    operation text NOT NULL CHECK (operation IN ('settle', 'release')),
    payload_fingerprint text NOT NULL,
    tokens bigint NOT NULL DEFAULT 0,
    cost_usd numeric(18, 8) NOT NULL DEFAULT 0,
    budget_after bigint,
    created_at timestamptz NOT NULL DEFAULT now()
);
