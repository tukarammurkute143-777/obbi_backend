"""Public blog endpoints. No auth: the pages must be crawlable for SEO. Only
published blogs are ever returned, and responses come from a 1-hour cache."""

from fastapi import APIRouter, HTTPException, Query, Request

from app.core.config import settings
from app.core.rate_limit import limiter
from app.services import blog_service
from app.services.blog_service import BlogError

router = APIRouter(prefix="/api/blogs", tags=["Blogs"])


@router.get("")
@limiter.limit(settings.RATE_LIMIT_PUBLIC)
async def list_blogs(
    request: Request,
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0, le=10000),
):
    """Published blogs, newest first (no article body; fetch it by slug)."""
    try:
        return await blog_service.public_list(limit, offset)
    except BlogError as e:
        raise HTTPException(status_code=e.status, detail=e.message)


@router.get("/{slug}")
@limiter.limit(settings.RATE_LIMIT_PUBLIC)
async def get_blog(request: Request, slug: str):
    try:
        return await blog_service.public_get(slug)
    except BlogError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
