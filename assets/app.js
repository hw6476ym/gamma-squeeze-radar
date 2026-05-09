// Gamma Squeeze Radar — front-end logic.
// Reads the static data.json the scraper writes and powers the dashboard.

const STATE = {
  raw: null,
  filtered: [],
  sortKey: "score",
  search: "",
  minScore: 0,
  category: "All",
  chart: null,
};

const CAT_ORDER = [
  "All", "Index ETF", "Sector ETF", "Bond ETF", "Commodity ETF",
  "Intl ETF", "AI/Semi", "Big Tech", "Fintech/Crypto", "Memestock",
  "Financials", "Industrial", "Auto", "Consumer", "Healthcare",
  "Energy", "Other",
];

// ── helpers ────────────────────────────────────────────────────────────
const fmt = {
  money: (v) => v == null ? "—" : (Math.abs(v) >= 1000 ? "$" + v.toLocaleString(undefined, {maximumFractionDigits:0}) : "$" + v.toFixed(2)),
  short: (v) => {
    if (v == null) return "—";
    const a = Math.abs(v);
    if (a >= 1e9) return (v / 1e9).toFixed(2) + "B";
    if (a >= 1e6) return (v / 1e6).toFixed(2) + "M";
    if (a >= 1e3) return (v / 1e3).toFixed(1) + "K";
    return v.toFixed(0);
  },
  pct: (v) => v == null ? "—" : (v >= 0 ? "+" : "") + v.toFixed(2) + "%",
  num: (v, d = 2) => v == null ? "—" : v.toLocaleString(undefined, {maximumFractionDigits: d, minimumFractionDigits: d}),
  int: (v) => v == null ? "—" : Math.round(v).toLocaleString(),
};

function fmtDate(iso) {
  // input: "2026-05-16" → "May 16"
  if (!iso) return "—";
  const d = new Date(iso + "T00:00:00Z");
  if (isNaN(d)) return iso;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

function fmtTimestamp(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function ago(iso) {
  const t = new Date(iso).getTime();
  const sec = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  return `${Math.floor(hr / 24)}d ago`;
}

// ── render ─────────────────────────────────────────────────────────────
function render() {
  const cards = document.getElementById("cards");
  const empty = document.getElementById("emptyState");
  cards.innerHTML = "";

  let list = [...STATE.raw.tickers];

  if (STATE.search) {
    const q = STATE.search.toUpperCase();
    list = list.filter((t) => t.ticker.includes(q));
  }
  if (STATE.minScore > 0) {
    list = list.filter((t) => t.score >= STATE.minScore);
  }
  if (STATE.category !== "All") {
    list = list.filter((t) => (t.category || "Other") === STATE.category);
  }

  const dirAsc = STATE.sortKey === "ticker" || STATE.sortKey === "distance_to_wall_pct";
  list.sort((a, b) => {
    const av = a[STATE.sortKey];
    const bv = b[STATE.sortKey];
    if (typeof av === "string") return dirAsc ? av.localeCompare(bv) : bv.localeCompare(av);
    if (STATE.sortKey === "distance_to_wall_pct") {
      // closest to wall = smallest positive distance
      const aa = av >= 0 ? av : 999;
      const bb = bv >= 0 ? bv : 999;
      return aa - bb;
    }
    return (bv ?? -Infinity) - (av ?? -Infinity);
  });

  STATE.filtered = list;
  empty.hidden = list.length > 0;

  const frag = document.createDocumentFragment();
  list.forEach((t, idx) => frag.appendChild(card(t, idx + 1)));
  cards.appendChild(frag);
}

function card(t, rank) {
  const el = document.createElement("article");
  el.className = "card";
  el.tabIndex = 0;
  el.setAttribute("role", "button");
  el.setAttribute("aria-label", `View details for ${t.ticker}`);
  el.dataset.ticker = t.ticker;

  const dist = t.distance_to_wall_pct;
  const distCls = dist == null ? "" : dist >= 0 && dist <= 6 ? "pos" : dist < 0 ? "neg" : "";

  const cat = t.category || "Other";
  const expRange = (t.expirations && t.expirations.length)
    ? `exp ${fmtDate(t.expirations[0])} – ${fmtDate(t.expirations[t.expirations.length - 1])}`
    : "";
  const dteRange = (t.dte_min != null && t.dte_max != null)
    ? `${t.dte_min}–${t.dte_max}d`
    : "";

  el.innerHTML = `
    <span class="rank">#${rank}</span>
    <div class="top">
      <div class="ticker">${t.ticker}</div>
      <div class="price">${fmt.money(t.spot)}</div>
    </div>
    <div class="meta-row">
      <span class="badge" data-cat="${cat}">${cat}</span>
      <span class="exp-range">${expRange} · ${dteRange}</span>
    </div>

    <div class="score">
      <span class="score-num">${t.score.toFixed(0)}</span>
      <div class="score-bar"><div style="width:${Math.max(2, t.score)}%"></div></div>
      <span class="score-label">score</span>
    </div>

    <div class="kvs">
      <div class="k">Call wall</div>      <div class="v">${fmt.money(t.call_wall)}</div>
      <div class="k">Δ to wall</div>      <div class="v ${distCls}">${fmt.pct(dist)}</div>
      <div class="k">Net GEX (1%)</div>   <div class="v ${t.net_gex >= 0 ? 'pos' : 'neg'}">${(t.net_gex >= 0 ? '+' : '') + fmt.short(t.net_gex)}</div>
      <div class="k">Call/put γ</div>     <div class="v">${fmt.num(t.call_put_ratio, 1)}×</div>
      <div class="k">Call vol</div>       <div class="v">${fmt.short(t.call_vol)}</div>
      <div class="k">Call OI</div>        <div class="v">${fmt.short(t.call_oi)}</div>
    </div>

    ${miniGexStrip(t)}
  `;

  el.addEventListener("click", () => openDetail(t));
  el.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openDetail(t);
    }
  });
  return el;
}

function miniGexStrip(t) {
  if (!t.profile || !t.profile.length) return "";
  const max = Math.max(...t.profile.map((p) => Math.max(p.call_gex, p.put_gex, 1)));
  // Pick a window of strikes centered on spot for the strip
  const visible = t.profile.slice(0, 30);
  const bars = visible.map((p) => {
    const callH = (p.call_gex / max) * 100;
    const putH = (p.put_gex / max) * 100;
    const isSpot = Math.abs(p.strike - t.spot) / t.spot < 0.01;
    if (isSpot) return `<div class="bar spot" title="spot ${fmt.money(t.spot)}"></div>`;
    const dom = p.call_gex >= p.put_gex
      ? `<div class="bar" style="height:${Math.max(1, callH)}%" title="$${p.strike} call γ ${fmt.short(p.call_gex)}"></div>`
      : `<div class="bar put" style="height:${Math.max(1, putH)}%" title="$${p.strike} put γ ${fmt.short(p.put_gex)}"></div>`;
    return dom;
  }).join("");
  return `<div class="gex-strip" aria-hidden="true">${bars}</div>`;
}

// ── detail modal ───────────────────────────────────────────────────────
function openDetail(t) {
  const dlg = document.getElementById("detail");
  const body = document.getElementById("detailBody");
  body.innerHTML = renderDetail(t);
  dlg.showModal();

  // build chart on next tick so canvas is in DOM
  requestAnimationFrame(() => buildChart(t));
}

function closeDetail() {
  const dlg = document.getElementById("detail");
  dlg.close();
  if (STATE.chart) { STATE.chart.destroy(); STATE.chart = null; }
}

function renderDetail(t) {
  const dist = t.distance_to_wall_pct;
  const flip = t.gamma_flip;
  const rows = (arr, kind) => arr.slice(0, 6).map((r) => `
    <tr class="${kind}-row">
      <td><span class="heat" style="background:${kind === 'call' ? 'var(--accent)' : 'var(--danger)'};opacity:${Math.max(0.2, (kind==='call'?r.call_gex:r.put_gex) / Math.max(1, arr[0][kind==='call'?'call_gex':'put_gex']))}"></span>${fmt.money(r.strike)}</td>
      <td>${fmt.short(kind === 'call' ? r.call_gex : r.put_gex)}</td>
      <td>${fmt.short(kind === 'call' ? r.call_oi : r.put_oi)}</td>
      <td>${fmt.short(kind === 'call' ? r.call_vol : r.put_vol)}</td>
    </tr>
  `).join("");

  const cat = t.category || "Other";
  const expirationRows = (t.by_expiration || []).map((e) => `
    <tr>
      <td>${fmtDate(e.expiration)} <span class="dim">(${e.dte ?? "—"}d)</span></td>
      <td class="${e.net_gex >= 0 ? 'pos' : 'neg'}">${(e.net_gex >= 0 ? "+" : "") + fmt.short(e.net_gex)}</td>
      <td class="pos">+${fmt.short(e.call_gex)}</td>
      <td class="neg">−${fmt.short(e.put_gex)}</td>
      <td>${fmt.short(e.call_oi)}</td>
      <td>${fmt.short(e.put_oi)}</td>
      <td>${fmt.short(e.call_vol)}</td>
      <td>${fmt.short(e.put_vol)}</td>
    </tr>
  `).join("");

  return `
  <div class="detail-body">
    <div class="detail-head">
      <span class="ticker">${t.ticker}</span>
      <span class="badge" data-cat="${cat}">${cat}</span>
      <span class="price">${fmt.money(t.spot)}</span>
      <span class="score-pill">score ${t.score.toFixed(0)} / 100</span>
    </div>

    <div class="detail-grid">
      <div class="metric"><div class="k">Call wall</div><div class="v">${fmt.money(t.call_wall)}</div></div>
      <div class="metric"><div class="k">Distance to wall</div><div class="v ${dist >= 0 && dist <= 6 ? 'pos' : ''}">${fmt.pct(dist)}</div></div>
      <div class="metric"><div class="k">Put wall</div><div class="v">${fmt.money(t.put_wall)}</div></div>
      <div class="metric"><div class="k">Gamma flip</div><div class="v">${flip ? fmt.money(flip) : "—"}</div></div>
      <div class="metric"><div class="k">Net GEX (1% move)</div><div class="v ${t.net_gex >= 0 ? 'pos' : 'neg'}">${(t.net_gex >= 0 ? '+' : '') + fmt.short(t.net_gex)}</div></div>
      <div class="metric"><div class="k">Call/put γ ratio</div><div class="v">${fmt.num(t.call_put_ratio, 1)}×</div></div>
      <div class="metric"><div class="k">Call vol / OI</div><div class="v">${fmt.short(t.call_vol)} / ${fmt.short(t.call_oi)}</div></div>
      <div class="metric"><div class="k">Avg IV (front 4)</div><div class="v">${t.avg_iv ? (t.avg_iv * 100).toFixed(1) + "%" : "—"}</div></div>
    </div>

    <div class="section-title">Gamma profile by strike (front 4 expirations, ±25% of spot)</div>
    <div class="chart-wrap"><canvas id="chartCanvas"></canvas></div>

    <div class="section-title">GEX broken down by expiration date</div>
    <table class="strikes-table" style="margin-bottom:18px;">
      <thead>
        <tr>
          <th>Expiration</th><th>Net GEX</th><th>Call γ</th><th>Put γ</th>
          <th>Call OI</th><th>Put OI</th><th>Call Vol</th><th>Put Vol</th>
        </tr>
      </thead>
      <tbody>${expirationRows || `<tr><td colspan="8" class="dim">no data</td></tr>`}</tbody>
    </table>

    <div style="display:grid; gap:18px; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));">
      <div>
        <div class="section-title">Top call-gamma strikes</div>
        <table class="strikes-table">
          <thead><tr><th>Strike</th><th>Call γ</th><th>Call OI</th><th>Vol</th></tr></thead>
          <tbody>${rows(t.top_call_strikes, "call")}</tbody>
        </table>
      </div>
      <div>
        <div class="section-title">Top put-gamma strikes</div>
        <table class="strikes-table">
          <thead><tr><th>Strike</th><th>Put γ</th><th>Put OI</th><th>Vol</th></tr></thead>
          <tbody>${rows(t.top_put_strikes, "put")}</tbody>
        </table>
      </div>
    </div>

    <p class="dim" style="font-size:12px; margin-top:18px;">
      Front 4 expirations: ${(t.expirations || []).map(fmtDate).join(" · ") || "—"}.
      <br/>GEX values are ≈ Σ contract gamma × OI × 100 × spot² × 1%, the dollar-delta
      market-makers must hedge per 1% spot move (positive = dealers long gamma).
    </p>
  </div>
  `;
}

function buildChart(t) {
  const ctx = document.getElementById("chartCanvas");
  if (!ctx || !window.Chart) return;
  if (STATE.chart) STATE.chart.destroy();

  const labels = t.profile.map((p) => p.strike);
  const callData = t.profile.map((p) => p.call_gex);
  const putData = t.profile.map((p) => -p.put_gex); // negative so they sit below the axis

  STATE.chart = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "Call γ exposure", data: callData, backgroundColor: "rgba(92,242,192,0.75)", borderColor: "rgba(92,242,192,1)", borderWidth: 1, stack: "g" },
        { label: "Put γ exposure",  data: putData,  backgroundColor: "rgba(255,92,122,0.75)", borderColor: "rgba(255,92,122,1)", borderWidth: 1, stack: "g" },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 250 },
      plugins: {
        legend: { labels: { color: "#8995b8", font: { size: 11 } } },
        tooltip: {
          backgroundColor: "#0b0f1a",
          borderColor: "#38456b",
          borderWidth: 1,
          callbacks: {
            title: (items) => "Strike $" + items[0].label,
            label: (ctx) => ctx.dataset.label + ": " + fmt.short(Math.abs(ctx.raw)),
          },
        },
        annotation: undefined, // would need plugin; we draw the spot line manually
      },
      scales: {
        x: {
          ticks: { color: "#8995b8", font: { size: 10 }, maxRotation: 0, autoSkip: true, maxTicksLimit: 12 },
          grid: { color: "rgba(35,44,74,0.4)" },
          title: { display: true, text: "Strike", color: "#5a6588", font: { size: 11 } },
        },
        y: {
          ticks: { color: "#8995b8", font: { size: 10 }, callback: (v) => fmt.short(Math.abs(v)) },
          grid: { color: "rgba(35,44,74,0.4)" },
          title: { display: true, text: "GEX ($/1% move)", color: "#5a6588", font: { size: 11 } },
        },
      },
    },
    plugins: [{
      id: "spot-line",
      afterDatasetsDraw(chart) {
        const xScale = chart.scales.x;
        // Find the closest label to spot
        let bestIdx = 0;
        let bestDiff = Infinity;
        labels.forEach((l, i) => {
          const d = Math.abs(l - t.spot);
          if (d < bestDiff) { bestDiff = d; bestIdx = i; }
        });
        const x = xScale.getPixelForValue(bestIdx);
        const yTop = chart.chartArea.top;
        const yBot = chart.chartArea.bottom;
        const ctx = chart.ctx;
        ctx.save();
        ctx.strokeStyle = "rgba(255,255,255,0.7)";
        ctx.setLineDash([4, 3]);
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(x, yTop);
        ctx.lineTo(x, yBot);
        ctx.stroke();
        ctx.fillStyle = "#fff";
        ctx.font = "11px ui-monospace, monospace";
        ctx.textAlign = "center";
        ctx.fillText("spot " + fmt.money(t.spot), x, yTop - 4);
        ctx.restore();
      },
    }],
  });
}

// ── boot ───────────────────────────────────────────────────────────────
async function boot() {
  try {
    const r = await fetch("data/data.json", { cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    STATE.raw = await r.json();
  } catch (e) {
    document.getElementById("cards").innerHTML = `
      <div class="callout">
        <h2>Couldn't load data.json</h2>
        <p>Run <code>python scripts/scrape.py</code> to generate it. (${e.message})</p>
      </div>`;
    return;
  }

  document.getElementById("updated").textContent =
    "data as of " + fmtTimestamp(STATE.raw.generated_at) + " (" + ago(STATE.raw.generated_at) + ")";
  document.getElementById("ticker-count").textContent =
    `${STATE.raw.ticker_count} tickers`;

  // Show the range of *nearest* expirations across the dataset — that's the
  // front edge of dealer-hedging windows people actually care about.
  const firsts = STATE.raw.tickers
    .map((t) => (t.expirations || [])[0])
    .filter(Boolean)
    .sort();
  if (firsts.length) {
    document.getElementById("exp-window").textContent =
      `nearest exp: ${fmtDate(firsts[0])} → ${fmtDate(firsts[firsts.length - 1])}`;
  } else {
    document.getElementById("exp-window").remove();
  }

  renderCategories();

  // wire controls
  document.getElementById("search").addEventListener("input", (e) => {
    STATE.search = e.target.value.trim();
    render();
  });
  document.getElementById("sort").addEventListener("change", (e) => {
    STATE.sortKey = e.target.value;
    render();
  });
  const minScore = document.getElementById("minScore");
  minScore.addEventListener("input", (e) => {
    STATE.minScore = +e.target.value;
    document.getElementById("minScoreVal").textContent = e.target.value;
    render();
  });

  // modal close
  const dlg = document.getElementById("detail");
  dlg.querySelector(".close").addEventListener("click", closeDetail);
  dlg.addEventListener("click", (e) => {
    const r = dlg.getBoundingClientRect();
    if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) {
      closeDetail();
    }
  });
  dlg.addEventListener("close", () => {
    if (STATE.chart) { STATE.chart.destroy(); STATE.chart = null; }
  });

  render();
}

function renderCategories() {
  const bar = document.getElementById("catBar");
  if (!bar) return;
  // Tally categories present in the data
  const counts = new Map();
  STATE.raw.tickers.forEach((t) => {
    const c = t.category || "Other";
    counts.set(c, (counts.get(c) || 0) + 1);
  });
  // Order: All first, then categories present, in canonical order, then any extras
  const cats = ["All"];
  CAT_ORDER.slice(1).forEach((c) => { if (counts.has(c)) cats.push(c); });
  Array.from(counts.keys()).forEach((c) => { if (!cats.includes(c)) cats.push(c); });

  bar.innerHTML = cats.map((c) => {
    const n = c === "All" ? STATE.raw.tickers.length : (counts.get(c) || 0);
    return `<button class="cat-chip${c === STATE.category ? ' active' : ''}" data-cat="${c}">${c}<span class="cnt">${n}</span></button>`;
  }).join("");

  bar.querySelectorAll(".cat-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      STATE.category = btn.dataset.cat;
      bar.querySelectorAll(".cat-chip").forEach((b) => b.classList.toggle("active", b === btn));
      render();
    });
  });
}

document.addEventListener("DOMContentLoaded", boot);
