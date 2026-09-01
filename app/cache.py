"""A small on-disk TTL cache plus one shared HTTP client.

Every provider goes through fetch_json(). That gives three things for free:
a single place to set the user agent and timeout, a cache so repeated searches
do not re-hit free public endpoints, and uniform failure handling - a provider
that is down returns None instead of raising, and the caller degrades.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from typing import Any

import httpx

from app.config import CACHE_DIR, HTTP_TIMEOUT, USER_AGENT

log = logging.getLogger("basis.cache")

_client: httpx.AsyncClient | None = None
_lock = asyncio.Lock()

# Process-lifetime counters, exposed at /api/metrics. Deliberately in memory and
# deliberately not per-user: the point is to notice an upstream going down or
# changing its data format, not to track anybody.
METRICS: dict[str, Any] = {
    "started_at": None,
    "match_requests": 0,
    "sources": {},
    "cfpb_resolution": {"attempted": 0, "matched": 0},
}


def record_source(key: str, outcome: str) -> None:
    """Count one upstream call outcome: live, cached, stale or failed."""
    counter = METRICS["sources"].setdefault(
        key, {"live": 0, "cached": 0, "stale": 0, "failed": 0}
    )
    if outcome in counter:
        counter[outcome] += 1


def record_cfpb_resolution(attempted: int, matched: int) -> None:
    """Track how many institutions reconcile to a CFPB company.

    A drop here is the signature of the name-matching bugs this project has
    already shipped twice, and it is invisible in the UI: unmatched banks just
    quietly stop carrying a complaint record. Watching the rate is how you find
    out before a user does.
    """
    METRICS["cfpb_resolution"]["attempted"] += attempted
    METRICS["cfpb_resolution"]["matched"] += matched


def metrics_snapshot() -> dict[str, Any]:
    res = METRICS["cfpb_resolution"]
    rate = round(res["matched"] / res["attempted"], 3) if res["attempted"] else None

    sources = {}
    for key, c in METRICS["sources"].items():
        total = sum(c.values())
        sources[key] = {
            **c,
            "total": total,
            "failure_rate": round(c["failed"] / total, 3) if total else 0.0,
        }

    return {
        "started_at": METRICS["started_at"],
        "match_requests": METRICS["match_requests"],
        "cfpb_match_rate": rate,
        "cfpb_resolution": dict(res),
        "sources": sources,
    }


async def gather_safe(*awaitables: Any, labels: list[str] | None = None) -> list[Any]:
    """Run awaitables concurrently, turning any exception into None.

    `asyncio.gather` propagates the first exception, so one provider raising
    would take down a page that nine sources feed. Providers already return
    None on failure; this is the backstop for the ones that raise instead,
    which is exactly the failure nobody predicts.
    """
    results = await asyncio.gather(*awaitables, return_exceptions=True)
    out: list[Any] = []
    for i, result in enumerate(results):
        if isinstance(result, BaseException):
            label = (labels or [])[i] if labels and i < len(labels) else f"task[{i}]"
            log.warning("%s raised %s: %s", label, type(result).__name__, result)
            out.append(None)
        else:
            out.append(result)
    return out


# Tracks which upstreams answered during the current request, so the UI can
# show the user exactly which sources were live and which were skipped.
class SourceLog:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def record(self, key: str, ok: bool, cached: bool, detail: str = "") -> None:
        self.entries.append({"source": key, "ok": ok, "cached": cached, "detail": detail})

    def as_list(self) -> list[dict[str, Any]]:
        return self.entries


async def get_client() -> httpx.AsyncClient:
    global _client
    async with _lock:
        if _client is None:
            _client = httpx.AsyncClient(
                timeout=HTTP_TIMEOUT,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                follow_redirects=True,
            )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


_URL_IN_TEXT = re.compile(r"https?://\S+")


def scrub(text: str) -> str:
    """Strip URLs out of an error message before it is logged.

    Some httpx exceptions embed the full request URL, and those URLs carry the
    user's ZIP code. Logging them would write a location trail to disk purely
    as a side effect of an upstream failing.
    """
    return _URL_IN_TEXT.sub("<url>", str(text))[:200]


def _cache_path(key: str, url: str, params: dict | None) -> Any:
    raw = f"{url}?{json.dumps(params or {}, sort_keys=True)}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return CACHE_DIR / f"{key}_{digest}.json"


def _read_cache(path, ttl: int) -> Any | None:
    try:
        if not path.exists():
            return None
        if time.time() - path.stat().st_mtime > ttl:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_cache(path, payload: Any) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    except Exception as exc:
        log.warning("cache write failed for %s: %s", path.name, exc)


async def fetch_json(
    key: str,
    url: str,
    params: dict | None = None,
    ttl: int = 3600,
    slog: SourceLog | None = None,
) -> Any | None:
    """Fetch and parse JSON, serving from cache when fresh.

    Returns None on any failure. Callers must treat None as 'this source was
    unavailable' and continue, never as 'the answer is empty'.
    """
    path = _cache_path(key, url, params)

    cached = _read_cache(path, ttl)
    if cached is not None:
        record_source(key, "cached")
        if slog:
            slog.record(key, ok=True, cached=True)
        return cached

    try:
        client = await get_client()
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        # Fall back to stale cache rather than losing the feature entirely.
        stale = _read_cache(path, ttl=10**9)
        if stale is not None:
            record_source(key, "stale")
            if slog:
                slog.record(key, ok=True, cached=True, detail="served stale after upstream error")
            log.warning("%s failed (%s), served stale cache", key, scrub(exc))
            return stale
        record_source(key, "failed")
        if slog:
            slog.record(key, ok=False, cached=False, detail=scrub(exc))
        log.warning("%s unavailable: %s", key, scrub(exc))
        return None

    _write_cache(path, data)
    record_source(key, "live")
    if slog:
        slog.record(key, ok=True, cached=False)
    return data
