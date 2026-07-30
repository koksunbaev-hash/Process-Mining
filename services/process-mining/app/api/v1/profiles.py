from __future__ import annotations

from fastapi import APIRouter, Request

from app.deps import ApiKeyDep
from app.schemas.logs import MappingProfileOut

router = APIRouter(prefix="/mapping-profiles", tags=["mapping"])


@router.get("", response_model=list[MappingProfileOut], summary="List activity mapping profiles")
async def list_profiles(request: Request, _: ApiKeyDep) -> list[MappingProfileOut]:
    return [
        MappingProfileOut(
            id=profile.id,
            description=profile.description,
            fallback=profile.fallback,
            rules=len(profile.rules),
            activities=profile.activities,
        )
        for profile in request.app.state.mappings.list()
    ]


@router.post("/reload", summary="Hot-reload profiles from the YAML config")
async def reload_profiles(request: Request, _: ApiKeyDep) -> dict[str, list[str]]:
    request.app.state.mappings.reload()
    return {"profiles": [p.id for p in request.app.state.mappings.list()]}
