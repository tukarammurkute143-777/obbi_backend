from fastapi import APIRouter, Depends, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool

from app.core.middleware import get_current_user, is_owner
from app.models.user import (
    ProfileResponse,
    UpdateProfileRequest,
    VisitHistoryResponse,
)
from app.services import user_service

router = APIRouter(prefix="/api/users", tags=["Users"])


@router.get("/me", response_model=ProfileResponse)
async def get_me(request: Request, user: dict = Depends(get_current_user)):
    """Current user's profile, resolved from the JWT."""
    return user_service.serialize_user(user, is_owner=is_owner(user))


@router.put("/me", response_model=ProfileResponse)
async def update_me(
    request: Request,
    body: UpdateProfileRequest,
    user: dict = Depends(get_current_user),
):
    """Update name / email / location. Mobile is fixed — it is the login identity."""
    changes = body.model_dump(exclude_none=True)

    if "email" in changes:
        taken = await run_in_threadpool(
            user_service.email_taken_by_other, changes["email"], str(user["id"])
        )
        if taken:
            raise HTTPException(
                status_code=409,
                detail="Ye email kisi dusre account pe already hai.",
            )

    # First real profile edit means they are no longer a fresh signup.
    if user.get("is_new_user"):
        changes["is_new_user"] = False

    try:
        updated = await run_in_threadpool(
            user_service.update_profile, str(user["id"]), changes
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return user_service.serialize_user(updated, is_owner=is_owner(updated))


@router.get("/visits", response_model=VisitHistoryResponse)
async def get_visits(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(get_current_user),
):
    """This user's successful login history, newest first."""
    return await run_in_threadpool(user_service.get_visit_history, user, limit)
