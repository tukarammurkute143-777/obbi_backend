from fastapi import APIRouter, Request, HTTPException
from app.models.auth import (
    SendOTPRequest,
    VerifyOTPRequest
)
from app.services.auth_service import send_otp, verify_otp

router = APIRouter(prefix="/api/auth", tags=["Auth"])

@router.post("/send-otp")
async def send_otp_endpoint(
    request: Request,
    body: SendOTPRequest
):
    ip = request.client.host
    result = await send_otp(body.mobile, ip)
    if not result['success']:
        raise HTTPException(status_code=400, detail=result['message'])
    return result

@router.post("/verify-otp")
async def verify_otp_endpoint(
    request: Request,
    body: VerifyOTPRequest
):
    ip = request.client.host
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