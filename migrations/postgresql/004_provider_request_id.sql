-- Correlates a gateway request with the upstream provider's request/completion ID.
ALTER TABLE provider_attempts
    ADD COLUMN IF NOT EXISTS provider_request_id text;
