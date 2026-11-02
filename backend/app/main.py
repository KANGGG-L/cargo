from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings, is_mock_mode
from app.routers import analytics

settings = get_settings()

app = FastAPI(title="HKG Cargo Control Tower API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analytics.router)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "llm_mode": "mock" if is_mock_mode() else "live",
        "model": settings.llm_model,
    }
