from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from app.api.routes.auth import router as auth_router

load_dotenv()

app = FastAPI(
    title="Obii Cabs API",
    description="Backend for Obii Cabs",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000",
                   "https://obbi-frontend.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth_router)

@app.get("/")
async def root():
    return {"message": "Obii Cabs API Running! 🚗"}

@app.get("/health")
async def health():
    return {"status": "healthy"}