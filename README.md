# newsagg — Personal News Aggregator

Self-hosted news aggregation service with an Android eink reader app.

## Architecture

```
[Ollama (local LLM)]
       ↕
[Python backend: FastAPI + DuckDB]   ←→   news.duckdb (embedded DB)
       ↕
[Android app: Go + Drift (eink UI)]
```

- **Backend** (`backend/`): fetches many source types → deduplicates with Ollama embeddings → clusters related stories → summarises with Ollama → exposes REST+SSE API with interaction tracking and personalised ranking
- **Android app** (`android/`): Go + [Drift](https://github.com/go-drift/drift) framework, eink-optimised paged display, gesture-driven navigation, offline bbolt cache

---

## Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Python | ≥ 3.11 | Backend runtime |
| [Ollama](https://ollama.ai) | any | Local LLM for summarisation + embeddings |
| Go | ≥ 1.22 | Android app |
| [Drift CLI](https://github.com/go-drift/drift) | latest | Build Android APK |
| `make` | any | Convenience targets (see below) |

---

## Quick Start (backend)

```bash
make backend-install   # create venv + install deps
make models            # pull mistral + nomic-embed-text from Ollama
make dev               # start backend on :8000 with auto-reload
```

Then verify:
```bash
curl http://localhost:8000/health
curl http://localhost:8000/sources
curl http://localhost:8000/feed
```

The backend registers itself as **`newsapp.local`** via mDNS (Zeroconf) on startup, so any device on the LAN can reach it at `http://newsapp.local:8000/`.

---

## Make Targets

```
make help                   Print this list
make backend-install        Create backend/venv and install Python deps
make models                 Pull required Ollama models (mistral, nomic-embed-text)
make dev                    Run backend in dev mode (auto-reload, :8000)
make run                    Run backend in production mode
make test                   Run Python test suite
make android-deps           Download Go module dependencies
make android-run            Run Android app on Linux desktop (preview)
make android-apk            Build Android APK via Drift CLI (local SDK required)
make android-install        Install APK to connected Android device via adb
make android-docker-build   Build Docker image with full Android SDK
make android-docker-apk     Build APK inside Docker → ./newsapp.apk
make docker-build           Build backend Docker image
make docker-run             Run backend in Docker (mounts ./data as DB volume)
make lint                   Run ruff linter on Python code
make clean                  Remove venv, __pycache__, *.duckdb
```

---

## Backend API Reference

| Method | Path | Description |
|---|---|---|
| GET | `/feed` | Paginated feed (`page`, `page_size`, `topics`, `since`, `active`) |
| GET | `/feed/live` | SSE stream of new cluster events |
| POST | `/items/{id}/read` | `{"duration_seconds": 30, "fully_read": true}` |
| POST | `/items/{id}/discard` | Discard + decrease topic interest |
| POST | `/items/{id}/expand` | Fetch deeper summary (triggers article scrape) |
| POST | `/items/{id}/follow` | Record link follow |
| POST | `/items/{id}/save` | Bookmark |
| POST | `/items/{id}/interest` | `{"direction": "up"\|"down"}` |
| GET | `/sources` | List all configured sources |
| POST | `/sources` | Add a source at runtime |
| DELETE | `/sources/{id}` | Disable a source |
| GET | `/topics` | Topic list with interest weights |
| GET | `/health` | Liveness check |

---

## Adding Sources

Edit `backend/config.toml`. Supported `type` values:

```toml
# RSS / Atom feed
[[sources]]
id = "ars"
type = "rss"
label = "Ars Technica"
url = "https://feeds.arstechnica.com/arstechnica/index"

# Google News search
[[sources]]
id = "gn_ai"
type = "google_news"
label = "Google News: AI"
query = "artificial intelligence"

# Hacker News (top stories by score)
[[sources]]
id = "hn"
type = "hackernews"
label = "Hacker News"
min_score = 50

# Reddit subreddit
[[sources]]
id = "r_prog"
type = "reddit"
label = "r/programming"
subreddit = "programming"
sort = "hot"
limit = 25

# Web scraper (article links from a page)
[[sources]]
id = "github_trending"
type = "scraper"
label = "GitHub Trending"
url = "https://github.com/trending"

# DuckDuckGo web search (no API key needed)
[[sources]]
id = "search_rust"
type = "search"
label = "Search: Rust"
query = "Rust programming language"
max_results = 10

# YouTube channel (fetches video list + transcripts)
[[sources]]
id = "yt_fireship"
type = "youtube"
label = "Fireship"
channel_id = "UCsBjURrPoezykLs9EqgamOA"

# Email newsletters via IMAP
[[sources]]
id = "newsletter"
type = "email_imap"
label = "Newsletters"
host = "imap.gmail.com"
user = "you@gmail.com"
password_env = "IMAP_PASSWORD"   # read from env var
folder = "Newsletters"
```

---

## Configuration Reference (`backend/config.toml`)

```toml
[server]
host = "0.0.0.0"
port = 8000
db_path = "news.duckdb"          # path to DuckDB file

[ollama]
base_url = "http://localhost:11434"
model = "mistral"                # summarisation model (runtime-configurable)
embed_model = "nomic-embed-text" # embedding model
summary_max_tokens = 200

[scheduler]
default_interval_seconds = 900   # starting fetch interval per source
min_interval_seconds = 60
max_interval_seconds = 86400
active_reader_boost = 0.25       # multiply interval by this when user is reading
breaking_news_threshold = 5      # stories on same topic within window = breaking
breaking_news_window_minutes = 10

[interest]
decay_rate = 0.01                # per-event global weight decay toward 0.5
learn_rate_read = 0.15
learn_rate_discard = -0.05
learn_rate_follow = 0.25
learn_rate_save = 0.30
learn_rate_interest_up = 0.20
learn_rate_interest_down = -0.15
```

---

## Web UI

A browser-based fallback UI is available at **`http://localhost:8000/`** (or **`http://newsapp.local:8000/`** on the LAN) once the backend is running. It mirrors the Android gesture model:

- **Tap left / right zones** or **← →** keys: previous/next page within item
- **Swipe up/down** or **J/K** keys: next/previous item
- **Swipe left** or **D**: discard item
- **Swipe right** or **E**: expand (fetch full summary + auto-discover RSS)
- **Long press** or **M**: context menu (save, send link, more/less like this, discard)
- **+/-**: interest up/down for current item's topics
- **R**: refresh feed
- **? or /**: open keyboard shortcut help overlay

Breaking news is pushed live via SSE and shown as a toast.

---

## Android App

```bash
make android-deps      # go mod download
make android-run       # preview on Linux desktop

# Default API URL is http://newsapp.local:8000 (mDNS)
# Override with:
export NEWSAGG_API=http://<server-ip>:8000
make android-apk       # build newsapp.apk (requires Drift CLI + Android SDK locally)
make android-install   # adb install newsapp.apk
```

### Build APK via Docker (no local Android SDK required)

```bash
make android-docker-build   # build Docker image with full SDK (one-time, ~2 GB)
make android-docker-apk     # build newsapp.apk inside Docker → ./newsapp.apk
make android-install        # adb install newsapp.apk
```

Or manually:
```bash
docker build -t newsagg-android -f android/Dockerfile .
docker run --rm -v "$PWD/out:/out" newsagg-android
adb install -r out/newsapp.apk
```

---

## Gesture Reference

| Gesture | Action |
|---|---|
| Tap left zone (≤35% width) | Previous page within item |
| Tap right zone (≥65% width) | Next page / advance |
| Swipe up | Next item |
| Swipe down | Previous item |
| Swipe left | Discard item (decreases topic interest) |
| Swipe right | Expand / read more (fetches full article summary) |
| Long press | Context menu: save, send link, more/less like this, discard |

---

## Production Deployment (systemd)

```bash
make install-systemd   # copies service file; follow prompts
```

Manual steps:
```bash
sudo useradd -r -s /bin/false newsagg
sudo mkdir -p /opt/newsagg /var/lib/newsagg
sudo chown newsagg: /opt/newsagg /var/lib/newsagg
sudo rsync -a backend/ /opt/newsagg/
sudo python3 -m venv /opt/newsagg/venv
sudo /opt/newsagg/venv/bin/pip install -e /opt/newsagg
# Edit /opt/newsagg/config.toml: set db_path = "/var/lib/newsagg/news.duckdb"
sudo cp backend/newsagg.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now newsagg
sudo journalctl -u newsagg -f
```

**Remote access:** [Tailscale](https://tailscale.com) creates a WireGuard mesh — no port forwarding needed. The Android app's default URL (`http://100.64.0.1:8000`) targets the Tailscale address range.

---

## Docker

```bash
make docker-build
make docker-run        # mounts ./data/ as DB volume, exposes :8000
```

Or manually:
```bash
cd backend
docker build -t newsagg .
docker run -d \
  -p 8000:8000 \
  -v "$(pwd)/../data:/data" \
  newsagg
```

Set `db_path = "/data/news.duckdb"` in `config.toml` when using Docker.

---

## How It Works

### Fetch pipeline
1. **Adaptive scheduler** polls each source on its own EMA-derived interval (sources that update frequently are polled more often; silent sources back off exponentially). When you are actively reading, all intervals are shortened by `active_reader_boost`.
2. **Fetcher** retrieves items and resolves redirect wrappers (Google News, t.co, bit.ly, etc.) to final canonical URLs before persisting to `raw_items`. HTML fetched during redirect resolution is scanned for RSS/Atom feeds, which are automatically added as sources.

### Deduplication pipeline (3 gates)
1. **Hash gate** — SHA-256 of normalised URL + title: instant O(1) duplicate skip.
2. **Embedding gate** — Ollama `nomic-embed-text` embedding, cosine similarity ≥ 0.92 against last 7 days of embeddings → mark duplicate.
3. **Cluster gate** — LLM prompt asks whether the item belongs to an existing nearby cluster (by embedding proximity). If confidence ≥ 0.70, append to cluster and re-summarise. Otherwise create a new cluster.

### Interest model
Every interaction (read, discard, follow, save, interest_up/down) updates per-topic weights in `interest_weights`. Weights decay toward 0.5 globally on each event. The feed is ranked by `0.4 × recency + 0.6 × interest`. Interest scores (0–100%) are shown in both the web UI and Android app.

### Read tracking
- Items are hidden from the feed once read (`read_at` is set).
- If a cluster receives new stories after being read, it reappears with an **UPDATE** badge.
- Expanding an item fetches a full article summary and also auto-discovers RSS feeds from that page.

### RSS autodiscovery
When expanding an item or resolving a redirect that returns HTML, the backend scans for `<link rel="alternate" type="application/rss+xml|atom+xml">` tags and automatically registers new feeds as sources.

---

## Project Layout

```
news/
├── Makefile
├── README.md
├── PLAN.md
├── backend/
│   ├── pyproject.toml
│   ├── config.toml              ← edit this to add sources
│   ├── newsagg.service          ← systemd unit
│   ├── Dockerfile
│   ├── migrations/
│   │   ├── 001_initial.sql
│   │   ├── 002_no_fk.sql        ← drops FK constraints for DuckDB compatibility
│   │   └── 003_read_tracking.sql ← adds read_at + is_update columns
│   └── newsagg/
│       ├── main.py              ← FastAPI app entry point
│       ├── config.py            ← TOML config loader
│       ├── db.py                ← DuckDB connection + migrations
│       ├── models.py            ← Pydantic models
│       ├── ranking.py           ← recency/interest scorer
│       ├── interest.py          ← interest weight updater
│       ├── api/
│       │   ├── feed.py          ← GET /feed, SSE /feed/live
│       │   ├── items.py         ← POST /items/{id}/*
│       │   ├── sources.py       ← GET/POST /sources
│       │   ├── topics.py        ← GET /topics
│       │   └── webui.py         ← GET /ui  (browser fallback UI)
│       ├── fetcher/
│       │   ├── scheduler.py     ← adaptive multi-threaded scheduler
│       │   ├── hashing.py       ← URL normalisation, dedup hashing, redirect resolution
│       │   ├── rss_discovery.py ← auto-discover RSS feeds from HTML pages
│       │   ├── rss.py
│       │   ├── google_news.py
│       │   ├── hackernews.py
│       │   ├── reddit.py
│       │   ├── scraper.py
│       │   ├── search.py
│       │   ├── youtube.py
│       │   └── email_imap.py
│       └── pipeline/
│           ├── dedup.py         ← 3-gate dedup + cluster assignment
│           ├── embed.py         ← Ollama embedding wrapper
│           ├── cluster.py       ← LLM cluster assignment
│           └── summarise.py     ← Ollama summarisation prompts
└── android/
    ├── Dockerfile               ← Docker build environment (full Android SDK)
    ├── drift.yaml               ← Drift app config (name, id, permissions)
    ├── go.mod
    ├── main.go                  ← app entry point (must be at root for Drift bridge)
    └── internal/
        ├── api/                 ← HTTP client + response models
        ├── cache/               ← bbolt offline cache
        ├── gesture/             ← tap zone + swipe classifier
        ├── ui/                  ← Drift widgets (theme, feed, item, menu)
        └── state/               ← page stack + app state
```
