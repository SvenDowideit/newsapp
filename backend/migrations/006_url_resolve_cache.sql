CREATE TABLE IF NOT EXISTS url_resolve_cache (
    original_url  VARCHAR PRIMARY KEY,
    resolved_url  VARCHAR NOT NULL,
    resolved_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
