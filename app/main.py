"""Basis - application entry point.

Serves the static site from /web and the JSON API from /api. Interactive API
docs are at /docs.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.cache import METRICS, close_client
from app.config import APP_NAME, APP_VERSION, CACHE_DIR, WEB_DIR
from app.routers import lookup, match

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)

# httpx logs every outbound request URL at INFO. Those URLs contain the user's
# ZIP code, so leaving it on writes a coarse location trail into the server log
# for no operational benefit. Failures are logged by app.cache with the source
# name and the error, which is what actually matters.
logging.getLogger("httpx").setLevel(logging.WARNING)

log = logging.getLogger("basis")


@asynccontextmanager
async def lifespan(app: FastAPI):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    METRICS["started_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    log.info("%s %s starting", APP_NAME, APP_VERSION)
    yield
    await close_client()


app = FastAPI(
    title=f"{APP_NAME} API",
    version=APP_VERSION,
    lifespan=lifespan,
    description=(
        "Loan eligibility estimates and real lender matching, built entirely on "
        "free public APIs. Not a credit decision and not an offer of credit."
    ),
)

# The page is entirely self-contained: no CDN, no analytics, no third-party
# script or font. That makes a strict policy free to adopt and worth having on
# a page where people type an income and a credit score.
CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'"
)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    # Nothing here needs a camera, a microphone or a location fix.
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=(), payment=()"
    # Applicant figures must never sit in a shared cache.
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    else:
        # Browsers will otherwise hold a stale script or stylesheet for hours
        # after a deploy, serving old behaviour from a page that looks current.
        # "no-cache" still allows caching, it just forces a revalidation, so
        # unchanged files still come back as a cheap 304.
        response.headers["Cache-Control"] = "no-cache"
    return response


app.include_router(match.router)
app.include_router(lookup.router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok", "app": APP_NAME, "version": APP_VERSION}


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
