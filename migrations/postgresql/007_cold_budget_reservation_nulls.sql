-- No usage row means zero usage, not NULL. A NULL in the admission predicate
-- evaluates to unknown and can admit concurrent reservations above the limit.
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
    SELECT
        COALESCE((SELECT tokens_used FROM token_budget_usage
                  WHERE client_id = p_client_id AND period = p_period), 0),
        COALESCE((SELECT cost_used_usd FROM token_budget_usage
                  WHERE client_id = p_client_id AND period = p_period), 0)
    INTO v_used_tokens, v_used_cost;
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
