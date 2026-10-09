-- Enforce non-negative budget counters for new writes without rewriting old data.
ALTER TABLE token_budget_usage
    ADD CONSTRAINT token_budget_usage_tokens_nonnegative CHECK (tokens_used >= 0) NOT VALID;

ALTER TABLE token_budget_usage
    ADD CONSTRAINT token_budget_usage_cost_nonnegative CHECK (cost_used_usd >= 0) NOT VALID;

ALTER TABLE token_budget_reservations
    ADD CONSTRAINT token_budget_reservations_tokens_nonnegative CHECK (tokens_reserved >= 0) NOT VALID;

ALTER TABLE token_budget_reservations
    ADD CONSTRAINT token_budget_reservations_cost_nonnegative CHECK (cost_reserved_usd >= 0) NOT VALID;
