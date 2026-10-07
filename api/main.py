"""
FastAPI application entry point.
Run with: uvicorn api.main:app --reload --port 8000
"""
import sys
import os

# Ensure the parent StatementParser directory is on the Python path
# so existing modules (db, loader, config, etc.) can be imported directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Clear Windows SSL key log env var to avoid SSL issues
os.environ.pop("SSLKEYLOGFILE", None)

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.deps import get_engine
from api.routers import transactions, categories, cards, notes


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Eagerly initialise DB connection and run migrations on startup
    get_engine()
    yield


app = FastAPI(
    title="StatementParser API",
    description="REST API for the HDFC Bank Statement Intelligence Dashboard",
    version="2.0.0",
    lifespan=lifespan,
)

# Allow the Next.js dev server (port 3000) and any localhost origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(transactions.router, prefix="/api")
app.include_router(categories.router, prefix="/api")
app.include_router(cards.router, prefix="/api")
# Two routers from one module: notes and LLM suggestions share the subject of a
# single transaction, and accepting a suggestion writes both.
app.include_router(notes.notes_router, prefix="/api")
app.include_router(notes.llm_router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok"}
