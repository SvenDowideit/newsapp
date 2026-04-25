# Personal News Aggregator — Implementation Plan

## Context

Build a self-hosted personal news aggregation service that reads from many source types, uses a local Ollama LLM to deduplicate, cluster, and summarise stories, and exposes a REST+SSE feed API. A companion Android app (Go + Drift framework) provides the primary reading UI, optimised for eink displays with a gesture-driven, paged interface. The backend tracks every interaction (read time, discards, follows, saves) to continuously personalise the feed ranking.

---

## Repository Layout

```
news/
├── backend/                        # Python FastAPI service
│   ├── pyproject.toml
│   ├── config.toml
│   ├── newsagg/
│   │   ├── main.py                 # FastAPI app + lifespan startup
│   │   ├── db.py                   # DuckDB connection + migration runner
│   │   ├── models.py               # Pydantic request/response models
│   │   ├── config.py               # TOML config loader
│   │   ├── ranking.py              # Combined recency/interest scorer
│   │   ├── interest.py             # Interest weight update logic
│   │   ├── api/
│   │   │   ├── feed.py             # GET /feed, SSE /feed/live
│   │   │   ├── items.py            # POST /items/{id}/* interaction events
│   │   │   ├── sources.py          # GET/POST /sources
│   │   │   └── topics.py           # GET /topics
│   │   ├── fetcher/
│   │   │   ├── scheduler.py        # Adaptive multi-threaded scheduler
│   │   │   ├── rss.py              # feedparser RSS/Atom
│   │   │   ├── scraper.py          # BS4 + Playwright for JS-heavy sites
│   │   │   ├── google_news.py      # Google News RSS endpoint
│   │   │   ├── search.py           # DuckDuckGo scraping
│   │   │   ├── hackernews.py       # HN Algolia API
│   │   │   ├── reddit.py           # Reddit JSON API (no OAuth)
│   │   │   ├── youtube.py          # youtube-transcript-api + channel RSS
│   │   │   └── email_imap.py       # IMAP newsletter ingestion
│   │   └── pipeline/
│   │       ├── dedup.py            # Hash → embedding → cluster gates
│   │       ├── embed.py            # Ollama /api/embeddings wrapper
│   │       ├── cluster.py          # LLM cluster assignment
│   │       └── summarise.py        # Ollama summarisation prompts
│   ├── migrations/
│   │   └── 001_initial.sql
│   ├── Dockerfile
│   └── newsagg.service             # systemd unit
│
└── android/                        # Go + Drift mobile app
    ├── go.mod
    ├── cmd/newsapp/main.go         # Entry point
    ├── internal/
    │   ├── api/
    │   │   ├── client.go           # HTTP client for backend REST
    │   │   └── models.go           # Go structs matching API responses
    │   ├── cache/
    │   │   └── store.go            # bbolt offline item cache
    │   ├── gesture/
    │   │   └── handler.go          # Tap zone + swipe + long-press classifier
    │   ├── ui/
    │   │   ├── theme.go            # Eink theme: black/white, large text
    │   │   ├── feedpage.go         # Feed list view
    │   │   ├── itempage.go         # Paged single-item reading view
    │   │   ├── contextmenu.go      # Long-press overlay menu
    │   │   └── sourcespage.go      # Source management
    │   └── state/
    │       └── app.go              # Page stack + app state
    └── android/
        └── AndroidManifest.xml
```

---

## Configuration Format: TOML (`config.toml`)

```toml
[server]
host = "0.0.0.0"
port = 8000
db_path = "/var/lib/newsagg/news.duckdb"

[ollama]
base_url = "http://localhost:11434"
model = "mistral"
embed_model = "nomic-embed-text"
summary_max_tokens = 200

[scheduler]
default_interval_seconds = 900
min_interval_seconds = 60
max_interval_seconds = 86400
active_reader_boost = 0.25        # multiply interval by this when user is reading
breaking_news_threshold = 5       # stories on same topic within window = breaking
breaking_news_window_minutes = 10

[interest]
decay_rate = 0.01
learn_rate_read = 0.15
learn_rate_discard = -0.05
learn_rate_follow = 0.25
learn_rate_save = 0.30

[[sources]]
id = "hn"
type = "hackernews"
label = "Hacker News"
min_score = 50

[[sources]]
id = "rss_ars"
type = "rss"
label = "Ars Technica"
url = "https://feeds.arstechnica.com/arstechnica/index"

[[sources]]
id = "google_news_ai"
type = "google_news"
query = "artificial intelligence"

[[sources]]
id = "reddit_programming"
type = "reddit"
subreddit = "programming"
sort = "hot"
```

---

## DuckDB Schema (`migrations/001_initial.sql`)

```sql
CREATE TABLE sources (
    id              VARCHAR PRIMARY KEY,
    type            VARCHAR NOT NULL,
    label           VARCHAR NOT NULL,
    config_json     JSON,
    enabled         BOOLEAN DEFAULT TRUE,
    last_fetched_at TIMESTAMPTZ,
    next_fetch_at   TIMESTAMPTZ,
    ema_interval_s  DOUBLE DEFAULT 900,
    ema_alpha       DOUBLE DEFAULT 0.3,
    consecutive_empty INTEGER DEFAULT 0,
    fetch_error_count INTEGER DEFAULT 0,
    last_error      VARCHAR
);

CREATE SEQUENCE seq_raw_items START 1;
CREATE TABLE raw_items (
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
CREATE INDEX idx_raw_items_content_hash ON raw_items(content_hash);
CREATE INDEX idx_raw_items_cluster_id   ON raw_items(cluster_id);

CREATE SEQUENCE seq_embeddings START 1;
CREATE TABLE embeddings (
    id          BIGINT PRIMARY KEY DEFAULT nextval('seq_embeddings'),
    raw_item_id BIGINT NOT NULL UNIQUE REFERENCES raw_items(id),
    model       VARCHAR NOT NULL,
    vector      FLOAT[],
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE SEQUENCE seq_clusters START 1;
CREATE TABLE clusters (
    id            BIGINT PRIMARY KEY DEFAULT nextval('seq_clusters'),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    first_seen_at TIMESTAMPTZ NOT NULL,
    latest_seen_at TIMESTAMPTZ NOT NULL,
    canonical_url VARCHAR,
    headline      VARCHAR NOT NULL,
    summary       VARCHAR NOT NULL,
    key_points    JSON,
    topics        VARCHAR[],
    source_ids    VARCHAR[],
    item_count    INTEGER DEFAULT 1,
    is_breaking   BOOLEAN DEFAULT FALSE,
    recency_score DOUBLE DEFAULT 0,
    interest_score DOUBLE DEFAULT 0,
    combined_score DOUBLE DEFAULT 0,
    scored_at     TIMESTAMPTZ
);
CREATE INDEX idx_clusters_combined_score ON clusters(combined_score DESC);

CREATE SEQUENCE seq_read_events START 1;
CREATE TABLE read_events (
    id               BIGINT PRIMARY KEY DEFAULT nextval('seq_read_events'),
    cluster_id       BIGINT NOT NULL REFERENCES clusters(id),
    event_type       VARCHAR NOT NULL,  -- read|discard|expand|follow|save|interest_up|interest_down
    occurred_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    duration_seconds INTEGER,
    fully_read       BOOLEAN,
    metadata_json    JSON
);
CREATE INDEX idx_read_events_cluster_id  ON read_events(cluster_id);
CREATE INDEX idx_read_events_occurred_at ON read_events(occurred_at);

CREATE TABLE interest_weights (
    topic        VARCHAR PRIMARY KEY,
    weight       DOUBLE NOT NULL DEFAULT 0.5,
    event_count  INTEGER DEFAULT 0,
    last_updated TIMESTAMPTZ DEFAULT now()
);
```

---

## API Routes

```
GET  /feed                         # paginated feed, ordered by combined_score
GET  /feed/live                    # SSE stream of new cluster events
POST /items/{id}/read              # body: {duration_seconds, fully_read}
POST /items/{id}/discard
POST /items/{id}/expand            # returns deeper summary / full article
POST /items/{id}/follow            # user tapped a link in the summary
POST /items/{id}/save
POST /items/{id}/interest          # body: {direction: "up"|"down"}
GET  /sources
POST /sources
GET  /topics
```

---

## Key Algorithms

### Adaptive Scheduler
Each source has `ema_interval_s` (EMA of time between fetches that yielded new items).

- New items found → update EMA with observed gap; reset `consecutive_empty`
- No new items → `consecutive_empty++`; backoff = `2^(consecutive_empty // 3)` × EMA, capped at max
- User actively reading (TTL=60s flag) → multiply next interval by `active_reader_boost` (0.25)
- Breaking news: coroutine queries clusters created in the last 10 min; if ≥5 on same topic, mark `is_breaking=TRUE` and push SSE event

Scheduler watcher runs every 10s:
```sql
SELECT id FROM sources
WHERE enabled = TRUE AND (next_fetch_at IS NULL OR next_fetch_at <= now())
ORDER BY next_fetch_at ASC NULLS FIRST LIMIT 10
```

### Deduplication Pipeline (3 gates)

1. **Hash gate** — `SHA256(normalise_url + "|" + normalise_title)` lookup in `raw_items.content_hash`. O(1).
2. **Embedding gate** — Compute Ollama embedding; cosine similarity (dot product on unit vectors) against embeddings from last 7 days. If top match ≥ 0.92, mark duplicate. FAISS `IndexFlatIP` sidecar when window > 10k rows.
3. **Cluster gate** — LLM prompt: given new item + 10 nearest cluster headlines by embedding, return `{cluster_id, confidence}`. If confidence ≥ 0.7, append to cluster and regenerate summary. Otherwise create new cluster.

### Interest Model
- One row per topic in `interest_weights` (weight 0–1, default 0.5)
- On each interaction: global decay pulls all weights toward 0.5 by 1%; then targeted delta applied to cluster's topics
- Learn rates: read +0.15, discard −0.05, follow +0.25, save +0.30, interest_up +0.20, interest_down −0.15

### Ranking
```
combined_score = 0.4 * recency_score + 0.6 * interest_score
recency_score  = exp(-age_in_seconds / 86400)
interest_score = avg(interest_weights.weight) for cluster's topics
```
Scores refreshed every 5 minutes or on interaction.

---

## Android App (Go + Drift)

**Framework:** [go-drift/drift](https://github.com/go-drift/drift) — Go mobile framework, Skia rendering, single codebase → Android + iOS.

**Eink UX principles:**
- No animations (causes eink ghosting)
- Pure black/white palette, ≥18sp body text
- Full-page flips only — no continuous scroll
- Text paginated at render time by measuring block heights vs screen height

**Gesture map:**

| Gesture | Action |
|---|---|
| Tap left zone (≤35% width) | Previous page within item / reduce interest |
| Tap right zone (≥65% width) | Next page / drill in / increase interest |
| Swipe up | Next item |
| Swipe down | Previous item |
| Swipe left | Discard (POST /items/{id}/discard) |
| Swipe right | Read more (POST /items/{id}/expand) |
| Long press (>600ms) | Context menu: send link, bookmark, save, adjust interest |

**Gesture classifier thresholds:** swipe min dist 60dp, tap max dist 15dp, long press 600ms.

**Offline cache:** bbolt (BoltDB), bucket `"items"`, 50 items prefetched on startup.

**State machine pages:** `PageFeed` → `PageItem` → `PageContextMenu`, `PageSources`

---

## Fetch Source Types

| Type | Implementation |
|---|---|
| RSS/Atom | feedparser |
| Web scraping | BeautifulSoup4 + Playwright (JS-heavy) |
| Google News | RSS: `news.google.com/rss/search?q=QUERY` |
| Web search | DuckDuckGo HTML scraping (no API key needed) |
| Hacker News | `hn.algolia.com/api/v1/search_by_date` |
| Reddit | `reddit.com/r/{sub}.json` (no auth) |
| YouTube | youtube-transcript-api + channel RSS |
| Email/newsletters | imaplib + email stdlib, BS4 for HTML body |
| GitHub trending | Scrape `github.com/trending` |
| Lobsters | `lobste.rs/rss` |
| arXiv | `export.arxiv.org/rss/cs.AI` (configurable categories) |
| Mastodon | Per-account RSS feeds |

---

## Backend Dependencies (`pyproject.toml`)

```toml
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "duckdb>=0.10",
    "feedparser>=6.0",
    "beautifulsoup4>=4.12",
    "playwright>=1.43",
    "httpx>=0.27",
    "sse-starlette>=2.0",
    "youtube-transcript-api>=0.6",
    "faiss-cpu>=1.8",
    "numpy>=1.26",
]
```

## Android Dependencies (`go.mod`)

```
require (
    github.com/go-drift/drift vX.Y.Z
    go.etcd.io/bbolt v1.3.9
)
```

---

## Deployment

Recommended: bare systemd services on a home server (Raspberry Pi 5 or x86 mini-PC).

```
[Ollama systemd]  ←→  [newsagg systemd]  ←→  [DuckDB file]
                              ↕
              [Android app over LAN / Tailscale VPN]
```

- Single uvicorn worker (DuckDB file lock; reads use DuckDB's multi-reader WAL mode)
- `newsagg.service` depends on `ollama.service`
- Remote access via Tailscale (no port forwarding needed)

Docker also supported: mount `/var/lib/newsagg` as a volume for DuckDB persistence.

---

## Build & Run

### Backend
```bash
cd backend
pip install -e ".[dev]"
ollama pull mistral && ollama pull nomic-embed-text
uvicorn newsagg.main:app --reload --host 0.0.0.0 --port 8000
```

### Android App
```bash
cd android
# dev build (host desktop)
go run ./cmd/newsapp
# Android APK via Drift CLI
drift build android
adb install newsapp.apk
```

---

## Critical Files (implementation order)

1. `backend/migrations/001_initial.sql` — schema foundation
2. `backend/newsagg/db.py` — DuckDB connection, migration runner, connection pool
3. `backend/newsagg/config.py` — TOML loader, source registry
4. `backend/newsagg/fetcher/scheduler.py` — adaptive scheduler, EMA logic, active-reader TTL
5. `backend/newsagg/pipeline/dedup.py` — three-gate dedup pipeline
6. `backend/newsagg/pipeline/summarise.py` — eink-optimised Ollama prompts
7. `backend/newsagg/ranking.py` — interest model + combined scorer
8. `backend/newsagg/main.py` — FastAPI app, lifespan, route registration
9. `android/internal/gesture/handler.go` — gesture classifier (core input layer)
10. `android/internal/ui/theme.go` + `itempage.go` — eink theme + paged display logic

---

## Verification

1. Start backend → `curl http://localhost:8000/feed` returns empty paginated response
2. Add an RSS source → scheduler fetches it within 15s → items appear in `/feed`
3. `curl -X POST http://localhost:8000/items/1/read -d '{"duration_seconds":30}'` → interest weight for item's topics updates
4. Two stories on same topic → dedup pipeline clusters them → `/feed` shows one item with `item_count=2` and merged summary
5. Android app connects, renders feed, gestures fire correct API calls (verify in backend logs)
6. Kill connectivity on phone → app serves from bbolt cache
