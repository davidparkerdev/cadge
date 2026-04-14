from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.services.session_store import _connect_db

logger = logging.getLogger(__name__)

_SETTINGS_TABLE = """
CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL DEFAULT '""',
    updated_at  TEXT NOT NULL
);
"""

DEFAULTS: dict[str, str] = {
    "summary.provider_id": "mlx-server",
    "summary.model": "",
}


async def init_settings_table() -> None:
    async with _connect_db() as db:
        await db.executescript(_SETTINGS_TABLE)
        await db.commit()
        now = datetime.now(timezone.utc).isoformat()
        for key, default_value in DEFAULTS.items():
            await db.execute(
                "INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                (key, json.dumps(default_value), now),
            )
        await db.commit()


async def get_setting(key: str) -> Optional[Any]:
    async with _connect_db() as db:
        cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        if row is None:
            default = DEFAULTS.get(key)
            return default
        try:
            return json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            return row[0]


async def set_setting(key: str, value: Any) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with _connect_db() as db:
        await db.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, json.dumps(value), now),
        )
        await db.commit()


async def get_all_settings() -> dict[str, Any]:
    result = dict(DEFAULTS)
    async with _connect_db() as db:
        cursor = await db.execute("SELECT key, value FROM settings")
        rows = await cursor.fetchall()
        for key, raw_value in rows:
            try:
                result[key] = json.loads(raw_value)
            except (json.JSONDecodeError, TypeError):
                result[key] = raw_value
    return result


async def get_feature_settings(feature: str) -> dict[str, Any]:
    prefix = f"{feature}."
    all_settings = await get_all_settings()
    return {
        k[len(prefix):]: v
        for k, v in all_settings.items()
        if k.startswith(prefix)
    }
