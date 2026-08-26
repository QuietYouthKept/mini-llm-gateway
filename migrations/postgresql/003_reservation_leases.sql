-- Durable reservation state machine and bounded crash-recovery lease.
ALTER TABLE token_budget_reservations
    ADD COLUMN IF NOT EXISTS state text NOT NULL DEFAULT 'reserved',
    ADD COLUMN IF NOT EXISTS expires_at timestamptz,
    ADD COLUMN IF NOT EXISTS settled_at timestamptz,
    ADD COLUMN IF NOT EXISTS released_at timestamptz;

ALTER TABLE token_budget_reservations
    DROP CONSTRAINT IF EXISTS token_budget_reservations_state_check;
ALTER TABLE token_budget_reservations
    ADD CONSTRAINT token_budget_reservations_state_check
    CHECK (state IN ('reserved', 'settled', 'released'));

-- Pre-lease rows are treated as short-lived in-flight work so an upgrade does
-- not retain abandoned reservations forever.
UPDATE token_budget_reservations
SET expires_at = created_at + interval '30 seconds'
WHERE expires_at IS NULL;
ALTER TABLE token_budget_reservations
    ALTER COLUMN expires_at SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_budget_reservations_expiry
ON token_budget_reservations (state, expires_at);

CREATE OR REPLACE FUNCTION try_reserve_token_budget(
    p_reservation_id text,
    p_client_id text,
    p_period text,
    p_tokens bigint,
    p_cost numeric,
    p_limit_tokens bigint,
    p_limit_cost numeric,
    p_lease_seconds integer
) RETURNS boolean
LANGUAGE plpgsql
AS $$
DECLARE
    v_used_tokens bigint;
    v_used_cost numeric;
    v_reserved_tokens bigint;
    v_reserved_cost numeric;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended(p_client_id || ':' || p_period, 0));
    SELECT COALESCE(tokens_used, 0), COALESCE(cost_used_usd, 0)
    INTO v_used_tokens, v_used_cost
    FROM token_budget_usage WHERE client_id = p_client_id AND period = p_period;
    SELECT COALESCE(sum(tokens_reserved), 0), COALESCE(sum(cost_reserved_usd), 0)
    INTO v_reserved_tokens, v_reserved_cost
    FROM token_budget_reservations
    WHERE client_id = p_client_id AND period = p_period AND state = 'reserved';
    IF v_used_tokens + v_reserved_tokens + p_tokens > p_limit_tokens
       OR (p_limit_cost > 0 AND v_used_cost + v_reserved_cost + p_cost > p_limit_cost)
    THEN RETURN false;
    END IF;
    INSERT INTO token_budget_reservations (
        reservation_id, client_id, period, tokens_reserved, cost_reserved_usd, expires_at
    ) VALUES (
        p_reservation_id, p_client_id, p_period, p_tokens, p_cost,
        now() + make_interval(secs => GREATEST(1, p_lease_seconds))
    );
    RETURN true;
END;
$$;
