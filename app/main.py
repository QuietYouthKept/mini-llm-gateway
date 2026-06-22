from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.startup import bootstrap
from app.interfaces.http.routes import health


@asynccontextmanager
async def lifespan(app: FastAPI):
    bootstrap()
    yield


app = FastAPI(
    title="mini-llm-gateway",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
