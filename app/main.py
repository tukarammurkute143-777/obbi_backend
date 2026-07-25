from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from slowapi.middleware import SlowAPIMiddleware

from app.core.config import settings
from app.core.middleware import IPBlockMiddleware, JWTAuthMiddleware
from app.core.rate_limit import RateLimitExceeded, limiter, rate_limit_handler
from app.api.routes.auth import router as auth_router
from app.api.routes.users import router as users_router
from app.api.routes.bookings import router as bookings_router
from app.api.routes.dashboard import router as dashboard_router

load_dotenv()

app = FastAPI(
    title="Obii Cabs API",
    description="Backend for Obii Cabs",
    version="1.0.0"
)

# SlowAPIMiddleware reads the limiter off app.state.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)

# Middleware order matters. add_middleware puts the most recently added
# outermost, so registering bottom-up here gives the request path:
#
#   CORS  ->  IP block  ->  rate limit  ->  JWT  ->  route
#
# CORS outermost so 401/403/429 replies still carry CORS headers (otherwise the
# browser reports an opaque network error instead of the real status). IP block
# before the rate limiter so banned callers never consume limiter storage, and
# the rate limiter before JWT so unauthenticated floods are throttled cheaply.
app.add_middleware(JWTAuthMiddleware)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(IPBlockMiddleware)
# Deployed frontend comes from FRONTEND_URL; localhost stays for local dev.
# dict.fromkeys dedupes while keeping order, since FRONTEND_URL is itself
# http://localhost:3000 in a local .env.
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(dict.fromkeys(
        [settings.FRONTEND_URL, "http://localhost:3000"]
    )),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(bookings_router)
app.include_router(dashboard_router)

@app.get("/")
async def root():
    return {"message": "Obii Cabs API Running! 🚗"}

@app.get("/health")
async def health():
    return {"status": "healthy"}
