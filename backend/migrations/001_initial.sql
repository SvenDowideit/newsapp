CREATE TABLE IF NOT EXISTS sources (
    id                VARCHAR PRIMARY KEY,
    type              VARCHAR NOT NULL,
    label             VARCHAR NOT NULL,
    config_json       JSON,
    enabled           BOOLEAN DEFAULT TRUE,
    last_fetched_at   TIMESTAMPTZ,
    next_fetch_at     TIMESTAMPTZ,
    ema_interval_s    DOUBLE DEFAULT 900,
    ema_alpha         DOUBLE DEFAULT 0.3,
    consecutive_empty INTEGER DEFAULT 0,
    fetch_error_count INTEGER DEFAULT 0,
    last_error        VARCHAR
);

CREATE SEQUENCE IF NOT EXISTS seq_raw_items START 1;
CREATE TABLE IF NOT EXISTS raw_items (
    id           BIGINT PRIMARY KEY DEFAULT nextval('seq_raw_items'),
    source_id    VARCHAR NOT NULL REFERENCES sources(id),
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    url          VARCHAR,
    title        VARCHAR,
    body_text    VARCHAR,
    author       VARCHAR,
    published_at TIMESTAMPTZ,
    url_hash     VARCHAR NOT NULL,
    title_hash   VARCHAR NOT NULL,
    content_hash VARCHAR NOT NULL,
    duplicate_of BIGINT,
    cluster_id   BIGINT,
    embed_id     BIGINT
);
CREATE INDEX IF NOT EXISTS idx_raw_items_content_hash ON raw_items(content_hash);
CREATE INDEX IF NOT EXISTS idx_raw_items_cluster_id   ON raw_items(cluster_id);
CREATE INDEX IF NOT EXISTS idx_raw_items_fetched_at   ON raw_items(fetched_at);

CREATE SEQUENCE IF NOT EXISTS seq_embeddings START 1;
CREATE TABLE IF NOT EXISTS embeddings (
    id          BIGINT PRIMARY KEY DEFAULT nextval('seq_embeddings'),
    raw_item_id BIGINT NOT NULL UNIQUE REFERENCES raw_items(id),
    model       VARCHAR NOT NULL,
    vector      FLOAT[],
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE SEQUENCE IF NOT EXISTS seq_clusters START 1;
CREATE TABLE IF NOT EXISTS clusters (
    id             BIGINT PRIMARY KEY DEFAULT nextval('seq_clusters'),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    first_seen_at  TIMESTAMPTZ NOT NULL,
    latest_seen_at TIMESTAMPTZ NOT NULL,
    canonical_url  VARCHAR,
    headline       VARCHAR NOT NULL,
    summary        VARCHAR NOT NULL,
    key_points     JSON,
    topics         VARCHAR[],
    source_ids     VARCHAR[],
    item_count     INTEGER DEFAULT 1,
    is_breaking    BOOLEAN DEFAULT FALSE,
    recency_score  DOUBLE DEFAULT 0,
    interest_score DOUBLE DEFAULT 0,
    combined_score DOUBLE DEFAULT 0,
    scored_at      TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_clusters_combined_score ON clusters(combined_score DESC);
CREATE INDEX IF NOT EXISTS idx_clusters_latest_seen_at ON clusters(latest_seen_at DESC);

CREATE SEQUENCE IF NOT EXISTS seq_read_events START 1;
CREATE TABLE IF NOT EXISTS read_events (
    id               BIGINT PRIMARY KEY DEFAULT nextval('seq_read_events'),
    cluster_id       BIGINT NOT NULL REFERENCES clusters(id),
    event_type       VARCHAR NOT NULL,
    occurred_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    duration_seconds INTEGER,
    fully_read       BOOLEAN,
    metadata_json    JSON
);
CREATE INDEX IF NOT EXISTS idx_read_events_cluster_id  ON read_events(cluster_id);
CREATE INDEX IF NOT EXISTS idx_read_events_occurred_at ON read_events(occurred_at);
CREATE INDEX IF NOT EXISTS idx_read_events_type        ON read_events(event_type);

CREATE TABLE IF NOT EXISTS interest_weights (
    topic        VARCHAR PRIMARY KEY,
    weight       DOUBLE NOT NULL DEFAULT 0.5,
    event_count  INTEGER DEFAULT 0,
    last_updated TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version    VARCHAR PRIMARY KEY,
    applied_at TIMESTAMPTZ DEFAULT now()
);
