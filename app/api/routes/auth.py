from fastapi import APIRouter, Request, HTTPException
from app.core.config import settings
from app.core.middleware import get_client_ip
from app.core.rate_limit import limiter
from app.models.auth import (
    SendOTPRequest,
    VerifyOTPRequest
)
from app.services.auth_service import send_otp, verify_otp

router = APIRouter(prefix="/api/auth", tags=["Auth"])

@router.post("/send-otp")
@limiter.limit(settings.RATE_LIMIT_SEND_OTP)
async def send_otp_endpoint(
    request: Request,
    body: SendOTPRequest
):
    ip = get_client_ip(request)
    result = await send_otp(body.mobile, ip)
    if not result['success']:
        raise HTTPException(status_code=400, detail=result['message'])
    return result

@router.post("/verify-otp")
@limiter.limit(settings.RATE_LIMIT_VERIFY_OTP)
async def verify_otp_endpoint(
    request: Request,
    body: VerifyOTPRequest
):
    ip = get_client_ip(request)
    result = await verify_otp(
        body.mobile,
        body.otp,
        ip,
        body.device_fingerprint,
        body.location
    )
    if not result['success']:
        raise HTTPException(status_code=400, detail=result['message'])
    return result

@router.get("/health")
async def auth_health():
    return {"status": "Auth service running! 🔐"}