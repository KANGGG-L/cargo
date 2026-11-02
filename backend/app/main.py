from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings, is_mock_mode
from app.routers import alerts, analytics, chat, documents, ingest, notifications, ops, orders, portal, settlement, shipments

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.ops import clock

    clock.ensure_task()
    yield
    clock.stop_task()


app = FastAPI(title="HKG Cargo Control Tower API", version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def access_log(request, call_next):
    import time as _time

    t0 = _time.perf_counter()
    response = await call_next(request)
    dur_ms = (_time.perf_counter() - t0) * 1000
    print(
        f'{{"event":"access","method":"{request.method}","path":"{request.url.path}",'
        f'"status":{response.status_code},"ms":{dur_ms:.1f}}}',
        flush=True,
    )
    return response


app.include_router(analytics.router)
app.include_router(chat.router)
app.include_router(shipments.router)
app.include_router(alerts.router)
app.include_router(ingest.router)
app.include_router(notifications.router)
app.include_router(orders.router)
app.include_router(documents.router)
app.include_router(portal.router)
app.include_router(settlement.router)
app.include_router(ops.router)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "llm_mode": "mock" if is_mock_mode() else "live",
        "model": settings.llm_model,
    }
