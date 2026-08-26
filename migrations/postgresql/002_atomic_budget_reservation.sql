-- Database-level admission primitive. Call inside a transaction.
-- The client advisory lock serializes a previously unseen period as well as an
-- existing usage row, avoiding the "no row to lock" race.

CREATE OR REPLACE FUNCTION try_reserve_token_budget(
    p_reservation_id text,
    p_client_id text,
    p_period text,
    p_tokens bigint,
    p_cost numeric,
    p_limit_tokens bigint,
    p_limit_cost numeric
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
    FROM token_budget_usage
    WHERE client_id = p_client_id AND period = p_period;

    SELECT COALESCE(sum(tokens_reserved), 0), COALESCE(sum(cost_reserved_usd), 0)
    INTO v_reserved_tokens, v_reserved_cost
    FROM token_budget_reservations
    WHERE client_id = p_client_id AND period = p_period;

    IF v_used_tokens + v_reserved_tokens + p_tokens > p_limit_tokens
       OR (p_limit_cost > 0 AND v_used_cost + v_reserved_cost + p_cost > p_limit_cost)
    THEN
        RETURN false;
    END IF;

    INSERT INTO token_budget_reservations (
        reservation_id, client_id, period, tokens_reserved, cost_reserved_usd
    ) VALUES (p_reservation_id, p_client_id, p_period, p_tokens, p_cost);
    RETURN true;
END;
$$;
