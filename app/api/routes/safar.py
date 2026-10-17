import logging
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from app.agents.supervisor import supervisor
from app.core.config import settings
from app.core.rate_limit import limiter

logger = logging.getLogger("safar")

router = APIRouter(prefix="/api/safar", tags=["Safar"])


@router.get("/route")
@limiter.limit(settings.RATE_LIMIT_SAFAR)
async def get_route(
    request: Request,
    origin: str = Query(..., alias="from", min_length=2, max_length=200),
    destination: str = Query(..., alias="to", min_length=2, max_length=200),
    detail: Literal["basic", "full", "multi"] = Query(
        "basic",
        description="basic: distance & time, full: + turn-by-turn waypoints, "
                    "multi: up to 3 route options",
    ),
):
    result = await supervisor.route(origin, destination, detail)
    if not result["success"]:
        raise HTTPException(
            status_code=result.get("status", 500), detail=result["message"]
        )
    return {**result, "from": origin.strip(), "to": destination.strip()}


@router.get("/hotels")
@limiter.limit(settings.RATE_LIMIT_SAFAR)
async def get_hotels(
    request: Request,
    destination: str = Query(..., min_length=2, max_length=100),
    type: Literal["all", "budget", "premium"] = Query(
        "all", description="all: near popular attractions, budget, or premium (luxury)"
    ),
    check_in: Optional[str] = Query(None, description="YYYY-MM-DD"),
    check_out: Optional[str] = Query(None, description="YYYY-MM-DD"),
    guests: int = Query(1, ge=1, le=20),
):
    result = await supervisor.hotel(destination, type, check_in, check_out, guests)
    if not result["success"]:
        raise HTTPException(
            status_code=result.get("status", 500), detail=result["message"]
        )
    return result
