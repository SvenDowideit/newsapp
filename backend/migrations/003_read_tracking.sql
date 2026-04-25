-- Track when each cluster was last fully read, and whether it's been updated since.
ALTER TABLE clusters ADD COLUMN IF NOT EXISTS read_at TIMESTAMPTZ;
ALTER TABLE clusters ADD COLUMN IF NOT EXISTS is_update BOOLEAN DEFAULT FALSE;

-- Index for efficient filtering of unread/updated clusters
CREATE INDEX IF NOT EXISTS idx_clusters_read_at ON clusters(read_at);
