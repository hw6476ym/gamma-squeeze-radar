# ⚡ Gamma Squeeze Radar

**Live ranking of stocks where dealer positioning is set up for a gamma squeeze.**

A small, fast static dashboard that:

1. Scrapes live options-chain data from [barchart.com](https://www.barchart.com)'s public proxy.
2. Computes per-strike **gamma exposure (GEX)** for each ticker's front 4 expirations.
3. Ranks tickers by a heuristic **squeeze score** (0–100) combining call/put gamma dominance, distance to the call wall, options-flow burst, and IV.
4. Renders a clean, dark-themed front-end with a Chart.js gamma-profile plot per ticker.

> ⚠️ **Not financial advice.** Educational visualization of public market data. Squeeze setups can dissipate in hours and small-float names move violently. Do your own work.

## What is a gamma squeeze?

When traders buy out-of-the-money **call options**, the market-makers who sold those calls go *short gamma*. As the underlying rallies toward those strikes, dealers' delta hedges balloon — they have to keep buying the stock to stay flat. Buying begets buying, and price gets sucked toward the largest call-gamma strike (the **call wall**). That's a gamma squeeze.

## Squeeze score

The 0–100 score blends four signals that the academic and practitioner literature (Squeezemetrics' 2020 GEX paper, the GME post-mortems, etc.) flag as squeeze prerequisites:

| Component | Why it matters | Max points |
|---|---|---|
| **Call/put gamma ratio** | Dealer hedging is one-sided when calls dominate | 35 |
| **Distance to call wall** | Squeeze leverage peaks ~3% below the wall | 30 |
| **Volume / OI burst** | Fresh positioning, not stale OI | 20 |
| **Implied volatility** | Vega-paranoid dealers hedge harder | 15 |

GEX itself is computed in the standard way:

```
GEX_strike  =  Σ contract_gamma × OI × 100 × spot² × 0.01
            ×  (+1 for calls, −1 for puts)
```

…summed across the front 4 expirations. The chart shows GEX in dollars-of-delta per 1% spot move.

## Run it locally

```bash
# 1. Refresh the data (writes data/data.json)
python scripts/scrape.py

# 2. Serve the static site
python -m http.server 5173
# open http://localhost:5173
```

No build step. No dependencies beyond the Python standard library.

## Deployment

The site is plain HTML/CSS/JS so any static host works. This repo is configured for **GitHub Pages** out of the box — pushing to `main` publishes automatically.

A daily GitHub Action (`.github/workflows/refresh.yml`) re-runs the scraper and commits a fresh `data/data.json` so the live site stays current without manual intervention.

## Architecture

```
gamma-squeeze-radar/
├── index.html          # entry point
├── assets/
│   ├── styles.css      # dark theme, no framework
│   └── app.js          # vanilla JS, Chart.js for the gamma-profile chart
├── data/
│   └── data.json       # scraped + computed payload (committed)
├── scripts/
│   └── scrape.py       # barchart proxy scraper + GEX math
└── .github/workflows/
    └── refresh.yml     # daily refresh job
```

## Caveats and limits

- **Barchart rate-limits aggressively.** The scraper sleeps ~1s between requests and retries 429s with exponential backoff. The universe is capped at 50 tickers per run.
- **GEX assumes dealer-neutral retail flow** (calls bought = dealer short, puts bought = dealer short). In reality some flow is dealer-initiated; treat the sign as a heuristic, not gospel.
- **Front 4 expirations only.** Longer-dated gamma matters less for hedging dynamics; this is the standard convention but it's a choice.
- **No after-hours data.** Run during US market hours for the freshest snapshot.

## License

MIT — see [LICENSE](LICENSE).
