from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException

from .. import db as database
from ..models import SourceInfo, SourceCreate

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("", response_model=list[SourceInfo])
async def list_sources():
    con = database.get()
    rows = con.execute(
        """
        SELECT id, type, label, enabled, last_fetched_at, next_fetch_at,
               ema_interval_s, fetch_error_count, last_error
        FROM sources
        ORDER BY label
        """
    ).fetchall()
    return [
        SourceInfo(
            id=r[0], type=r[1], label=r[2], enabled=r[3],
            last_fetched_at=r[4], next_fetch_at=r[5],
            ema_interval_s=r[6] or 900,
            fetch_error_count=r[7] or 0,
            last_error=r[8],
        )
        for r in rows
    ]


@router.post("", response_model=SourceInfo, status_code=201)
async def add_source(body: SourceCreate):
    con = database.get()
    existing = con.execute("SELECT id FROM sources WHERE id = ?", [body.id]).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail="Source ID already exists")
    con.execute(
        "INSERT INTO sources (id, type, label, config_json) VALUES (?, ?, ?, ?)",
        [body.id, body.type, body.label, json.dumps(body.config)],
    )
    return SourceInfo(
        id=body.id, type=body.type, label=body.label, enabled=True,
        last_fetched_at=None, next_fetch_at=None,
        ema_interval_s=900, fetch_error_count=0, last_error=None,
    )


@router.delete("/{source_id}", status_code=204)
async def disable_source(source_id: str):
    con = database.get()
    con.execute("UPDATE sources SET enabled = FALSE WHERE id = ?", [source_id])
