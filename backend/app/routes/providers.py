from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from app.services.providers.registry import get_provider, list_providers, get_provider_info

router = APIRouter(prefix="/api/providers", tags=["providers"])


@router.get("")
async def get_providers():
    providers = list_providers()
    return [asdict(p) for p in providers]


@router.get("/{provider_id}")
async def get_provider_detail(provider_id: str):
    info = get_provider_info(provider_id)
    if not info:
        raise HTTPException(status_code=404, detail="Provider not found")
    return asdict(info)


@router.get("/{provider_id}/models")
async def get_provider_models(provider_id: str):
    provider = get_provider(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    models = await provider.list_models()
    return [asdict(m) for m in models]


@router.get("/{provider_id}/status")
async def get_provider_status(provider_id: str):
    provider = get_provider(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    return await provider.check_status()
