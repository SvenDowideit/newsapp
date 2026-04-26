CREATE TABLE IF NOT EXISTS rss_scan_log (
    url         VARCHAR PRIMARY KEY,
    scanned_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    feeds_found INTEGER NOT NULL DEFAULT 0
);
