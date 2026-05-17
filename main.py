from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.logging import logger, setup_logging
from app.db.engine import engine
from app.db.init_db import init_db
from app.routers import upload, samples


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs once at startup and once at shutdown.
    Initialises DB tables and connection pool; disposes pool on exit.
    """
    setup_logging()
    logger.info("Starting MDA API...")
    await init_db()
    logger.info("Connection pool ready.")
    yield
    await engine.dispose()
    logger.info("Connection pool closed.")


app = FastAPI(
    title="MDA Data Ingestion API",
    description="Ingest, version, and query clinical sample records.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router)
app.include_router(samples.router)


@app.get("/health", tags=["meta"])
async def health() -> dict:
    return {"status": "ok"}
