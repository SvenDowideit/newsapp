from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    db_path: str = "news.duckdb"


@dataclass
class OllamaConfig:
    base_url: str = "http://localhost:11434"
    model: str = "mistral"
    embed_model: str = "nomic-embed-text"
    summary_max_tokens: int = 200


@dataclass
class SchedulerConfig:
    default_interval_seconds: int = 900
    min_interval_seconds: int = 60
    max_interval_seconds: int = 86400
    active_reader_boost: float = 0.25
    breaking_news_threshold: int = 5
    breaking_news_window_minutes: int = 10


@dataclass
class GeographyConfig:
    # Maps place name -> interest weight (0.0-1.0) for each geographic level.
    # Matching is case-insensitive and partial.
    # 0.5 = neutral, higher = boost, lower = suppress.
    city: dict[str, float] = field(default_factory=dict)
    state: dict[str, float] = field(default_factory=dict)
    country: dict[str, float] = field(default_factory=dict)
    region: dict[str, float] = field(default_factory=dict)


@dataclass
class RankingConfig:
    """Tune how source diversity, novelty, and volume affect scoring."""
    source_diversity_weight: float = 0.12
    source_novelty_weight: float = 0.20
    source_novelty_halflife: float = 50.0
    low_volume_boost_weight: float = 0.10
    source_diversity_window_days: int = 7


@dataclass
class InterestConfig:
    decay_rate: float = 0.01
    learn_rate_read: float = 0.15
    learn_rate_discard: float = -0.05
    learn_rate_follow: float = 0.25
    learn_rate_save: float = 0.30
    learn_rate_interest_up: float = 0.20
    learn_rate_interest_down: float = -0.15

    def rate_for(self, event_type: str) -> float:
        mapping = {
            "read": self.learn_rate_read,
            "discard": self.learn_rate_discard,
            "follow": self.learn_rate_follow,
            "save": self.learn_rate_save,
            "interest_up": self.learn_rate_interest_up,
            "interest_down": self.learn_rate_interest_down,
        }
        return mapping.get(event_type, 0.0)


@dataclass
class SourceConfig:
    id: str
    type: str
    label: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Config:
    server: ServerConfig = field(default_factory=ServerConfig)
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    ranking: RankingConfig = field(default_factory=RankingConfig)
    interest: InterestConfig = field(default_factory=InterestConfig)
    geography: GeographyConfig = field(default_factory=GeographyConfig)
    sources: list[SourceConfig] = field(default_factory=list)


def load(path: str | Path = "config.toml") -> Config:
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    cfg = Config()

    if s := raw.get("server"):
        cfg.server = ServerConfig(**s)
    if o := raw.get("ollama"):
        cfg.ollama = OllamaConfig(**o)
    if sc := raw.get("scheduler"):
        cfg.scheduler = SchedulerConfig(**sc)
    if r := raw.get("ranking"):
        cfg.ranking = RankingConfig(**r)
    if i := raw.get("interest"):
        cfg.interest = InterestConfig(**i)
    if g := raw.get("geography"):
        cfg.geography = GeographyConfig(
            city=g.get("city", {}),
            state=g.get("state", {}),
            country=g.get("country", {}),
            region=g.get("region", {}),
        )

    for src in raw.get("sources", []):
        src = dict(src)
        sid = src.pop("id")
        stype = src.pop("type")
        slabel = src.pop("label")
        cfg.sources.append(SourceConfig(id=sid, type=stype, label=slabel, extra=src))

    return cfg
