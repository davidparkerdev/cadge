"""Frontend log ingestion endpoint.

Receives structured log entries from the Stargate frontend and writes them
to the backend logger, giving persistent visibility into client-side errors.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/logs", tags=["logs"])
logger = logging.getLogger("stargate.frontend")


class LogEntry(BaseModel):
    ts: str
    level: str
    category: str
    message: str
    data: Optional[dict] = None
    error: Optional[str] = None


@router.post("")
async def ingest_log(entry: LogEntry):
    """Receive a frontend log entry and write it to the backend log."""
    prefix = f"[{entry.category}]"
    detail = entry.error or ""
    text = f"{prefix} {entry.message}" + (f" | {detail}" if detail else "")

    level = entry.level.lower()
    if level == "error":
        logger.error(text)
    elif level == "warn":
        logger.warning(text)
    elif level == "info":
        logger.info(text)
    else:
        logger.debug(text)

    return {"ok": True}
