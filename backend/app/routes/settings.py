from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.settings_store import get_all_settings, get_setting, set_setting

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingUpdate(BaseModel):
    value: str | int | float | bool | None


@router.get("")
async def list_settings():
    return await get_all_settings()


@router.get("/{key:path}")
async def get_setting_value(key: str):
    value = await get_setting(key)
    return {"key": key, "value": value}


@router.put("/{key:path}")
async def update_setting(key: str, body: SettingUpdate):
    await set_setting(key, body.value)
    return {"key": key, "value": body.value}
