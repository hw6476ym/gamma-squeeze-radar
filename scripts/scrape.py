"""Gamma Squeeze Radar — barchart options scraper.

Pulls live options-chain data from barchart's public proxy API and computes
gamma-exposure (GEX) and squeeze-potential metrics for each ticker. Output is
written to data/data.json which the static front-end reads.

Run: python scripts/scrape.py
"""

from __future__ import annotations

import json
import math
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "data.json"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

BC_BASE = "https://www.barchart.com"
PROXY = f"{BC_BASE}/proxies/core-api/v1/options/get"

# Watchlist seed — categorized so the front-end can filter / colour-code.
# Universe is unioned with barchart's most-active list at runtime, so this
# is the floor of what's always covered, not a ceiling.
SEED: dict[str, str] = {
    # ── Index & broad ETFs (huge dealer gamma books) ─────────────────────
    "SPY": "Index ETF", "QQQ": "Index ETF", "IWM": "Index ETF",
    "DIA": "Index ETF", "VOO": "Index ETF", "VTI": "Index ETF",
    # Bonds & rates
    "TLT": "Bond ETF", "HYG": "Bond ETF", "LQD": "Bond ETF",
    # Sector ETFs
    "XLF": "Sector ETF", "XLE": "Sector ETF", "XLK": "Sector ETF",
    "XLV": "Sector ETF", "XLI": "Sector ETF", "XLY": "Sector ETF",
    "XBI": "Sector ETF", "SMH": "Sector ETF", "SOXX": "Sector ETF",
    "ARKK": "Sector ETF", "IBIT": "Sector ETF",
    # Commodities
    "GLD": "Commodity ETF", "SLV": "Commodity ETF",
    "USO": "Commodity ETF", "UNG": "Commodity ETF",
    # International
    "EEM": "Intl ETF", "FXI": "Intl ETF", "EWZ": "Intl ETF",
    # ── AI / semis (where most of the 2025–26 gamma flow has lived) ──────
    "NVDA": "AI/Semi", "AMD": "AI/Semi", "AVGO": "AI/Semi",
    "TSM": "AI/Semi", "ASML": "AI/Semi", "MU": "AI/Semi",
    "INTC": "AI/Semi", "MRVL": "AI/Semi", "ARM": "AI/Semi",
    "QCOM": "AI/Semi", "SMCI": "AI/Semi", "ANET": "AI/Semi",
    "AI": "AI/Semi", "PLTR": "AI/Semi", "IONQ": "AI/Semi",
    "RGTI": "AI/Semi", "SOUN": "AI/Semi", "BBAI": "AI/Semi",
    "PATH": "AI/Semi", "CRWD": "AI/Semi", "NOW": "AI/Semi",
    "SNOW": "AI/Semi", "DDOG": "AI/Semi",
    # ── Big tech ─────────────────────────────────────────────────────────
    "AAPL": "Big Tech", "MSFT": "Big Tech", "GOOGL": "Big Tech",
    "META": "Big Tech", "AMZN": "Big Tech", "NFLX": "Big Tech",
    "TSLA": "Big Tech", "ORCL": "Big Tech", "CRM": "Big Tech",
    "ADBE": "Big Tech", "SHOP": "Big Tech",
    # ── Fintech / crypto / memestocks ────────────────────────────────────
    "COIN": "Fintech/Crypto", "MSTR": "Fintech/Crypto",
    "MARA": "Fintech/Crypto", "RIOT": "Fintech/Crypto",
    "HOOD": "Fintech/Crypto", "SOFI": "Fintech/Crypto",
    "AFRM": "Fintech/Crypto", "PYPL": "Fintech/Crypto",
    "SQ":   "Fintech/Crypto",
    "GME":  "Memestock", "AMC": "Memestock", "BYND": "Memestock",
    "RIVN": "Memestock", "LCID": "Memestock", "CVNA": "Memestock",
    "DKNG": "Memestock", "BABA": "Memestock",
    # ── Other heavies often in flow ──────────────────────────────────────
    "BAC": "Financials", "JPM": "Financials", "WFC": "Financials",
    "BA": "Industrial", "GE": "Industrial", "F": "Auto", "GM": "Auto",
    "DIS": "Consumer", "NKE": "Consumer", "WBD": "Consumer",
    "PFE": "Healthcare", "LLY": "Healthcare", "UNH": "Healthcare",
    "XOM": "Energy", "CVX": "Energy",
}
SEED_TICKERS = list(SEED.keys())

CHAIN_FIELDS = (
    "symbol,baseSymbol,baseLastPrice,strikePrice,expirationDate,daysToExpiration,"
    "volume,openInterest,delta,gamma,impliedVolatility,symbolType"
)

ACTIVE_FIELDS = (
    "symbol,baseSymbol,baseLastPrice,symbolType,strikePrice,expirationDate,"
    "daysToExpiration,volume,openInterest,impliedVolatilityRank1y"
)


# ---------------------------------------------------------------------------
# Network plumbing
# ---------------------------------------------------------------------------


class Session:
    """Tiny cookie-jar wrapper that talks to barchart's XSRF-protected proxy."""

    def __init__(self) -> None:
        self.cookies: dict[str, str] = {}
        self.xsrf: str = ""

    def _cookie_header(self) -> str:
        return "; ".join(f"{k}={v}" for k, v in self.cookies.items())

    def _absorb_cookies(self, headers: list[tuple[str, str]]) -> None:
        for k, v in headers:
            if k.lower() != "set-cookie":
                continue
            piece = v.split(";", 1)[0]
            if "=" not in piece:
                continue
            name, val = piece.split("=", 1)
            self.cookies[name.strip()] = val.strip()

    def warm_up(self, ticker: str = "MU") -> None:
        url = f"{BC_BASE}/stocks/quotes/{ticker}/gamma-exposure"
        req = Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
        with urlopen(req, timeout=30) as resp:
            resp.read()
            self._absorb_cookies(resp.headers.items())
        token = self.cookies.get("XSRF-TOKEN", "")
        self.xsrf = urllib.parse.unquote(token)
        if not self.xsrf:
            raise RuntimeError("Failed to obtain XSRF token from barchart")

    def get_json(self, url: str, referer: str, retries: int = 3) -> dict[str, Any]:
        backoff = 2.0
        last_err: Exception | None = None
        for attempt in range(retries):
            req = Request(
                url,
                headers={
                    "User-Agent": UA,
                    "Accept": "application/json",
                    "X-XSRF-TOKEN": self.xsrf,
                    "Referer": referer,
                    "Cookie": self._cookie_header(),
                },
            )
            try:
                with urlopen(req, timeout=45) as resp:
                    payload = resp.read()
                    self._absorb_cookies(resp.headers.items())
                return json.loads(payload.decode("utf-8"))
            except HTTPError as e:
                last_err = e
                if e.code == 429:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                raise
            except URLError as e:
                last_err = e
                time.sleep(backoff)
                backoff *= 2
        raise last_err if last_err else RuntimeError("get_json failed")


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------


def fetch_most_active(sess: Session, limit: int = 80) -> list[str]:
    """Return distinct base tickers from barchart's most-active-options board."""
    qs = urllib.parse.urlencode(
        {
            "fields": ACTIVE_FIELDS,
            "orderBy": "volume",
            "orderDir": "desc",
            "between(volume,500,)": "",
            "between(daysToExpiration,1,)": "",
            "hasOptions": "true",
            "page": 1,
            "limit": 250,
            "raw": 1,
        }
    )
    data = sess.get_json(f"{PROXY}?{qs}", f"{BC_BASE}/options/most-active/stocks")
    seen: list[str] = []
    # Only skip leveraged / inverse ETFs — they're not real gamma exposure,
    # they're rebalanced derivatives. Major index, sector, bond, commodity
    # ETFs are kept because that's where dealer-positioning matters most.
    skip_leveraged = {
        "SQQQ", "TQQQ", "SPXS", "SPXL", "SOXL", "SOXS", "TZA", "TNA",
        "BOIL", "KOLD", "FAS", "FAZ", "UVXY", "SVXY", "VXX", "UPRO",
        "SPXU", "SDOW", "UDOW", "TMF", "TMV", "DUST", "NUGT", "JNUG",
        "JDST", "LABU", "LABD", "YINN", "YANG", "ERX", "ERY", "GUSH",
        "DRIP", "DPST", "WEBL", "WEBS", "BITX", "ETHU",
    }
    for r in data.get("data", []):
        sym = (r.get("baseSymbol") or "").upper().strip()
        if not sym or sym in seen or sym in skip_leveraged:
            continue
        # Skip indices / odd symbols (we want plain tradable underlyings)
        if not re.fullmatch(r"[A-Z]{1,5}", sym):
            continue
        seen.append(sym)
        if len(seen) >= limit:
            break
    return seen


def fetch_chain(sess: Session, ticker: str) -> list[dict[str, Any]]:
    qs = urllib.parse.urlencode(
        {
            "symbol": ticker,
            "fields": CHAIN_FIELDS,
            "groupBy": "",
            "hasOptions": "true",
            "raw": 1,
        }
    )
    referer = f"{BC_BASE}/stocks/quotes/{ticker}/options"
    data = sess.get_json(f"{PROXY}?{qs}", referer)
    return data.get("data", []) or []


# ---------------------------------------------------------------------------
# GEX math
# ---------------------------------------------------------------------------


def _f(val: Any) -> float:
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).replace(",", "").replace("%", "").strip()
    if not s or s in {"-", "N/A"}:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def compute_metrics(ticker: str, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Boil an options chain down to gamma-squeeze headline metrics.

    GEX (per 1% move) ≈ Σ contract_gamma × OI × 100 × spot² × 0.01, signed
    +1 for calls / -1 for puts (the standard dealer-positioning convention).
    """

    # Use the raw block when present — it has the unformatted floats
    chain: list[dict[str, Any]] = []
    spot = 0.0
    for r in rows:
        raw = r.get("raw") or r
        spot = max(spot, _f(raw.get("baseLastPrice")))
        chain.append(raw)
    if not chain or spot <= 0:
        return None

    # Limit to the front 4 expirations — that's where dealer hedging concentrates
    expirations = sorted({c.get("expirationDate", "") for c in chain if c.get("expirationDate")})
    front = expirations[:4]
    front_set = set(front)

    # Per-expiration DTE lookup (use first row we see for each expiration)
    dte_by_exp: dict[str, int] = {}
    for c in chain:
        e = c.get("expirationDate")
        if e in front_set and e not in dte_by_exp:
            try:
                dte_by_exp[e] = int(_f(c.get("daysToExpiration")))
            except Exception:
                pass

    by_strike: dict[float, dict[str, float]] = {}
    by_exp: dict[str, dict[str, float]] = {
        e: {"call_gex": 0.0, "put_gex": 0.0, "call_oi": 0, "put_oi": 0,
            "call_vol": 0, "put_vol": 0}
        for e in front
    }
    call_gex_total = 0.0
    put_gex_total = 0.0
    call_oi_total = 0
    put_oi_total = 0
    call_vol_total = 0
    put_vol_total = 0
    iv_samples: list[float] = []

    for c in chain:
        exp = c.get("expirationDate")
        if exp not in front_set:
            continue
        gamma = _f(c.get("gamma"))
        oi = int(_f(c.get("openInterest")))
        vol = int(_f(c.get("volume")))
        strike = _f(c.get("strikePrice"))
        iv = _f(c.get("impliedVolatility"))
        sym_type = str(c.get("symbolType") or "").lower()
        is_call = "call" in sym_type or sym_type == "c"
        if oi == 0 and vol == 0:
            continue
        if iv > 0:
            iv_samples.append(iv)

        # GEX per 1% move, in $ of delta
        gex_contract = gamma * oi * 100.0 * spot * spot * 0.01
        bucket = by_strike.setdefault(
            strike,
            {"call_gex": 0.0, "put_gex": 0.0, "call_oi": 0, "put_oi": 0,
             "call_vol": 0, "put_vol": 0},
        )
        eb = by_exp[exp]
        if is_call:
            call_gex_total += gex_contract
            call_oi_total += oi
            call_vol_total += vol
            bucket["call_gex"] += gex_contract
            bucket["call_oi"] += oi
            bucket["call_vol"] += vol
            eb["call_gex"] += gex_contract
            eb["call_oi"] += oi
            eb["call_vol"] += vol
        else:
            put_gex_total += gex_contract
            put_oi_total += oi
            put_vol_total += vol
            bucket["put_gex"] += gex_contract
            bucket["put_oi"] += oi
            bucket["put_vol"] += vol
            eb["put_gex"] += gex_contract
            eb["put_oi"] += oi
            eb["put_vol"] += vol

    if not by_strike:
        return None

    net_gex = call_gex_total - put_gex_total

    # Call wall = strike with biggest call GEX *above* spot — dealers hedge
    # short-gamma exposure by buying as price approaches it.
    above = [(k, v) for k, v in by_strike.items() if k >= spot]
    call_wall = max(above, key=lambda kv: kv[1]["call_gex"])[0] if above else 0.0
    put_wall_below = [(k, v) for k, v in by_strike.items() if k <= spot]
    put_wall = max(put_wall_below, key=lambda kv: kv[1]["put_gex"])[0] if put_wall_below else 0.0

    # Walk strikes in order, find sign change of cumulative net-GEX (gamma flip)
    sorted_strikes = sorted(by_strike.keys())
    running = 0.0
    flip_strike = 0.0
    prev_running = 0.0
    prev_strike = sorted_strikes[0] if sorted_strikes else spot
    for k in sorted_strikes:
        b = by_strike[k]
        running += b["call_gex"] - b["put_gex"]
        if prev_running <= 0 < running or prev_running >= 0 > running:
            flip_strike = (prev_strike + k) / 2
        prev_running = running
        prev_strike = k

    # Distance to call wall as a % of spot — closer = more squeeze leverage
    dist_to_wall = ((call_wall - spot) / spot * 100.0) if call_wall else 0.0

    # Gamma-squeeze score (0–100) — heuristic combining the factors that
    # academic and practitioner literature (e.g. Squeezemetrics 2020 white paper,
    # GME post-mortems) flag as squeeze prerequisites.
    score = 0.0
    # Call dominance — net positive call gamma above put gamma
    cp_ratio = call_gex_total / put_gex_total if put_gex_total > 1e-6 else 5.0
    score += min(35.0, cp_ratio * 12.0)
    # Proximity to call wall (peaks at ~3% above spot)
    if 0 < dist_to_wall <= 15:
        score += 30.0 * (1 - abs(dist_to_wall - 3.0) / 12.0)
    elif dist_to_wall <= 0:
        score += 8.0  # already above the wall, less squeeze juice
    # Volume burst — call volume vs OI signals fresh positioning
    if call_oi_total > 0:
        burst = call_vol_total / call_oi_total
        score += min(20.0, burst * 25.0)
    # Implied vol floor — needs enough IV that market-makers care
    if iv_samples:
        avg_iv = sum(iv_samples) / len(iv_samples)
        if avg_iv > 0.4:
            score += min(15.0, (avg_iv - 0.4) * 30.0)

    score = max(0.0, min(100.0, score))

    # Top 5 call-gamma strikes for the per-ticker drilldown
    top_call_strikes = sorted(
        ({"strike": k, **{kk: v[kk] for kk in v}} for k, v in by_strike.items() if v["call_gex"] > 0),
        key=lambda r: r["call_gex"],
        reverse=True,
    )[:8]
    top_put_strikes = sorted(
        ({"strike": k, **{kk: v[kk] for kk in v}} for k, v in by_strike.items() if v["put_gex"] > 0),
        key=lambda r: r["put_gex"],
        reverse=True,
    )[:8]

    # Gamma profile — strikes within ±25% of spot, for the chart
    profile = []
    lo, hi = spot * 0.75, spot * 1.25
    for k in sorted_strikes:
        if not (lo <= k <= hi):
            continue
        b = by_strike[k]
        profile.append({
            "strike": round(k, 2),
            "call_gex": round(b["call_gex"], 2),
            "put_gex": round(b["put_gex"], 2),
            "net_gex": round(b["call_gex"] - b["put_gex"], 2),
            "call_oi": int(b["call_oi"]),
            "put_oi": int(b["put_oi"]),
        })

    # Per-expiration breakdown (front 4) for the detail drilldown
    by_expiration = []
    for e in front:
        b = by_exp[e]
        by_expiration.append({
            "expiration": e,                 # ISO yyyy-mm-dd
            "dte": dte_by_exp.get(e),
            "call_gex": round(b["call_gex"], 2),
            "put_gex":  round(b["put_gex"], 2),
            "net_gex":  round(b["call_gex"] - b["put_gex"], 2),
            "call_oi":  int(b["call_oi"]),
            "put_oi":   int(b["put_oi"]),
            "call_vol": int(b["call_vol"]),
            "put_vol":  int(b["put_vol"]),
        })

    return {
        "ticker": ticker,
        "category": SEED.get(ticker, "Other"),
        "spot": round(spot, 2),
        "score": round(score, 1),
        "net_gex": round(net_gex, 2),
        "call_gex": round(call_gex_total, 2),
        "put_gex": round(put_gex_total, 2),
        "call_put_ratio": round(cp_ratio, 2),
        "call_wall": round(call_wall, 2),
        "put_wall": round(put_wall, 2),
        "gamma_flip": round(flip_strike, 2) if flip_strike else None,
        "distance_to_wall_pct": round(dist_to_wall, 2),
        "call_oi": call_oi_total,
        "put_oi": put_oi_total,
        "call_vol": call_vol_total,
        "put_vol": put_vol_total,
        "avg_iv": round(sum(iv_samples) / len(iv_samples), 4) if iv_samples else None,
        "expirations": front,                 # front 4, ISO order
        "dte_min": min(dte_by_exp.values()) if dte_by_exp else None,
        "dte_max": max(dte_by_exp.values()) if dte_by_exp else None,
        "by_expiration": by_expiration,
        "top_call_strikes": [
            {k: (round(v, 2) if isinstance(v, float) else v) for k, v in row.items()}
            for row in top_call_strikes
        ],
        "top_put_strikes": [
            {k: (round(v, 2) if isinstance(v, float) else v) for k, v in row.items()}
            for row in top_put_strikes
        ],
        "profile": profile,
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def gather(target_count: int = 80, max_universe: int = 90) -> list[dict[str, Any]]:
    sess = Session()
    print("warming up barchart session…", file=sys.stderr)
    sess.warm_up()

    print("fetching most-active options…", file=sys.stderr)
    universe: list[str] = []
    try:
        universe = fetch_most_active(sess)
    except Exception as e:  # noqa: BLE001
        print(f"  most-active fetch failed: {e}", file=sys.stderr)

    # Union with seed list, preserving most-active priority
    for s in SEED_TICKERS:
        if s not in universe:
            universe.append(s)
    universe = universe[:max_universe]
    print(f"universe: {len(universe)} tickers", file=sys.stderr)

    results: list[dict[str, Any]] = []
    for i, t in enumerate(universe, 1):
        print(f"  [{i}/{len(universe)}] {t}…", file=sys.stderr, end=" ")
        try:
            rows = fetch_chain(sess, t)
            metrics = compute_metrics(t, rows)
            if metrics:
                results.append(metrics)
                print(f"score={metrics['score']:.1f}", file=sys.stderr)
            else:
                print("no data", file=sys.stderr)
        except (HTTPError, URLError, json.JSONDecodeError, RuntimeError) as e:
            print(f"err: {e}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"err: {e}", file=sys.stderr)
        time.sleep(0.6)  # be polite — barchart rate-limits aggressively

    results.sort(key=lambda r: r["score"], reverse=True)
    return results


def main() -> int:
    results = gather()
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "barchart.com (public proxy)",
        "ticker_count": len(results),
        "tickers": results,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT} ({OUT.stat().st_size:,} bytes, {len(results)} tickers)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
