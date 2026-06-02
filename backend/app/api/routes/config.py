"""Configuration endpoints.

Read the active config, preview-validate a candidate payload, and apply it.
Applying is rejected if it would loosen risk limits during a Live session, and
every accepted change is versioned into ``configuration_versions``.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config.manager import ConfigError
from app.config.schema import AppConfig
from app.db.models import ConfigurationVersion
from app.db.session import get_session
from app.runtime import get_runtime

router = APIRouter(prefix="/api/config", tags=["config"])


class ApplyConfigRequest(BaseModel):
    config: dict
    note: str | None = None


@router.get("")
async def get_config() -> dict:
    rt = get_runtime()
    return {
        "version": rt.config_manager.version_hash,
        "config": rt.config.model_dump(mode="json"),
    }


@router.post("/validate")
async def validate_config(req: ApplyConfigRequest) -> dict:
    rt = get_runtime()
    try:
        cfg = rt.config_manager.validate_payload(req.config)
    except ConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"ok": True, "normalized": cfg.model_dump(mode="json")}


@router.post("/apply")
async def apply_config(req: ApplyConfigRequest) -> dict:
    rt = get_runtime()
    try:
        cfg: AppConfig = rt.config_manager.validate_payload(req.config)
        version = rt.config_manager.apply(cfg, active_mode=rt.mode_manager.mode)
    except ConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    with get_session() as s:
        s.query(ConfigurationVersion).update({ConfigurationVersion.is_active: False})
        s.add(
            ConfigurationVersion(
                version_hash=version,
                payload=cfg.model_dump(mode="json"),
                is_active=True,
                note=req.note or "applied via API",
            )
        )
        s.commit()
    return {"ok": True, "version": version}
