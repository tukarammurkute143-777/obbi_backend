import logging
from typing import Literal

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
