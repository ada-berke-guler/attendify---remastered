from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.redis import close_redis
from app.services.qr_rotator import run_rotator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("attendify")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    if settings.FACE_MODE == "mock":
        logger.warning(
            "FACE_MODE=mock: embeddings come from image hashes, not a face model. "
            "Do not use this for real attendance."
        )
    stop = asyncio.Event()
    rotator = asyncio.create_task(run_rotator(stop)) if settings.QR_ROTATOR_ENABLED else None
    try:
        yield
    finally:
        stop.set()
        if rotator is not None:
            await rotator
        await close_redis()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "Attendify: QR + face recognition + liveness attendance.\n\n"
        "Security flow: rotating QR nonce (Redis) → blink challenge → single-use liveness "
        "ticket (Redis, GETDEL) → 1:1 face match in PostgreSQL with pgvector."
    ),
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# Same-origin deployment (Caddy serves the SPA and proxies /api), so no CORS by default.
# DEV_CORS_ORIGINS opens it for the Vite dev server only.
if settings.dev_cors_origins:
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.dev_cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router, prefix="/api/v1")


@app.get("/api/health", tags=["Health"], summary="Liveness probe")
def health() -> dict:
    return {"status": "ok", "version": settings.APP_VERSION, "face_mode": settings.FACE_MODE}
