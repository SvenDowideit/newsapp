-- DuckDB does not support ALTER TABLE ... DROP CONSTRAINT.
-- Recreate the three affected tables without FK constraints.
-- Referential integrity is enforced in application code.

-- embeddings: drop FK on raw_item_id
CREATE TABLE embeddings_new (
    id          BIGINT PRIMARY KEY DEFAULT nextval('seq_embeddings'),
    raw_item_id BIGINT NOT NULL UNIQUE,
    model       VARCHAR NOT NULL,
    vector      FLOAT[],
    created_at  TIMESTAMPTZ DEFAULT now()
);
INSERT INTO embeddings_new SELECT * FROM embeddings;
DROP TABLE embeddings;
ALTER TABLE embeddings_new RENAME TO embeddings;

-- raw_items: drop FK on source_id
CREATE TABLE raw_items_new (
    id           BIGINT PRIMARY KEY DEFAULT nextval('seq_raw_items'),
    source_id    VARCHAR NOT NULL,
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
INSERT INTO raw_items_new SELECT * FROM raw_items;
DROP TABLE raw_items;
ALTER TABLE raw_items_new RENAME TO raw_items;
CREATE INDEX IF NOT EXISTS idx_raw_items_content_hash ON raw_items(content_hash);
CREATE INDEX IF NOT EXISTS idx_raw_items_cluster_id   ON raw_items(cluster_id);
CREATE INDEX IF NOT EXISTS idx_raw_items_fetched_at   ON raw_items(fetched_at);

-- read_events: drop FK on cluster_id
CREATE TABLE read_events_new (
    id               BIGINT PRIMARY KEY DEFAULT nextval('seq_read_events'),
    cluster_id       BIGINT NOT NULL,
    event_type       VARCHAR NOT NULL,
    occurred_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    duration_seconds INTEGER,
    fully_read       BOOLEAN,
    metadata_json    JSON
);
INSERT INTO read_events_new SELECT * FROM read_events;
DROP TABLE read_events;
ALTER TABLE read_events_new RENAME TO read_events;
CREATE INDEX IF NOT EXISTS idx_read_events_cluster_id  ON read_events(cluster_id);
CREATE INDEX IF NOT EXISTS idx_read_events_occurred_at ON read_events(occurred_at);
CREATE INDEX IF NOT EXISTS idx_read_events_type        ON read_events(event_type);
