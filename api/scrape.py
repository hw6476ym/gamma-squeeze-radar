"""Vercel Python serverless endpoint — /api/scrape

If you deploy this repo to Vercel, the front-end will call this endpoint
instead of the static data/data.json snapshot. Each request runs the scraper
live and returns fresh dealer-positioning data.

Vercel's free tier gives 10s/100s execution windows; a 90-ticker scrape is
borderline. We cap to 30 tickers per request by default to stay well inside
the budget. Bump SCRAPE_LIMIT in your Vercel env vars to override.

Local test:  vercel dev   (then GET http://localhost:3000/api/scrape)
"""

from __future__ import annotations

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path

# Make sibling scripts/ importable
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scrape as scraper  # noqa: E402

# In-process cache so we don't re-scrape on every cold/warm request — the
# barchart proxy will rate-limit us if every Vercel hit re-runs the full job.
_CACHE: dict[str, object] = {"payload": None, "ts": 0.0}
TTL_SEC = int(os.environ.get("SCRAPE_TTL_SEC", "300"))   # 5 min default
LIMIT   = int(os.environ.get("SCRAPE_LIMIT",   "30"))    # tickers per call


def _payload() -> dict:
    now = time.time()
    cached = _CACHE.get("payload")
    if cached and (now - float(_CACHE["ts"])) < TTL_SEC:
        return cached  # type: ignore[return-value]
    payload = scraper.gather_payload(target_count=LIMIT, max_universe=LIMIT)
    payload["cache_ttl_sec"] = TTL_SEC
    payload["live"] = True
    _CACHE["payload"] = payload
    _CACHE["ts"] = now
    return payload


class handler(BaseHTTPRequestHandler):  # Vercel's required entry-point name
    def do_GET(self) -> None:  # noqa: N802
        try:
            payload = _payload()
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", f"public, max-age={TTL_SEC}, s-maxage={TTL_SEC}")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:  # noqa: BLE001
            err = json.dumps({"error": str(e), "type": type(e).__name__}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(err)))
            self.end_headers()
            self.wfile.write(err)
