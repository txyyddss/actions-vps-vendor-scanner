from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.misc.logger import get_logger


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Aggregate Buying Dashboard</title>
  <link rel="stylesheet" href="assets/style.css">
</head>
<body data-theme="dark">
  <div class="grid-bg"></div>
  <main class="page">
    <header class="hero">
      <div>
        <h1>Aggregate Buying Dashboard</h1>
        <p>Live VPS inventory from WHMCS, HostBill, and API-driven vendors.</p>
      </div>
      <div class="hero-actions">
        <button id="theme-toggle">Toggle Theme</button>
      </div>
    </header>
    <section class="stats" id="stats"></section>
    <section class="table-wrap">
      <table id="products-table">
        <thead>
          <tr>
            <th data-sort="site">Site</th>
            <th data-sort="name">Product</th>
            <th data-sort="platform">Platform</th>
            <th data-sort="status">Status</th>
            <th data-sort="price">Price</th>
            <th data-sort="updated">Updated</th>
            <th>Buy</th>
          </tr>
        </thead>
        <tbody id="products-body"></tbody>
      </table>
    </section>
    <footer>
      <small id="last-updated"></small>
    </footer>
  </main>
  <script>window.__DASHBOARD_DATA__ = __DATA__;</script>
  <script src="assets/app.js"></script>
</body>
</html>
"""


CSS_TEMPLATE = """:root {
  --bg: #070a11;
  --bg-elev: #111723;
  --line: #1f2c43;
  --text: #d3e4ff;
  --muted: #89a4d1;
  --accent: #03f5c4;
  --danger: #ff4d6d;
  --ok: #1ce870;
}
body[data-theme="light"] {
  --bg: #eef3fc;
  --bg-elev: #ffffff;
  --line: #cfd8ea;
  --text: #14233d;
  --muted: #5e6e8e;
  --accent: #007ea7;
  --danger: #b3002d;
  --ok: #087f37;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  font-family: "Space Grotesk", "Sora", "Segoe UI", sans-serif;
  background: radial-gradient(circle at top right, rgba(3,245,196,0.12), transparent 42%), var(--bg);
  color: var(--text);
}
.grid-bg {
  position: fixed;
  inset: 0;
  background-image: linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px);
  background-size: 24px 24px;
  pointer-events: none;
}
.page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 1.2rem;
}
.hero {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  align-items: flex-start;
  background: var(--bg-elev);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 1rem;
}
.hero h1 { margin: 0 0 0.4rem; font-size: clamp(1.3rem, 3vw, 2rem); }
.hero p { margin: 0; color: var(--muted); }
button {
  border: 1px solid var(--line);
  background: transparent;
  color: var(--text);
  padding: 0.6rem 0.9rem;
  border-radius: 10px;
  cursor: pointer;
}
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 0.8rem;
  margin-top: 0.9rem;
}
.stat {
  background: var(--bg-elev);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 0.8rem;
}
.stat .label { color: var(--muted); font-size: 0.8rem; }
.stat .value { font-size: 1.2rem; font-weight: 700; margin-top: 0.2rem; }
.table-wrap {
  margin-top: 0.9rem;
  overflow-x: auto;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--bg-elev);
}
table {
  width: 100%;
  border-collapse: collapse;
}
th, td {
  text-align: left;
  padding: 0.7rem;
  border-bottom: 1px solid var(--line);
  font-size: 0.9rem;
}
th { color: var(--muted); cursor: pointer; user-select: none; }
.status {
  display: inline-flex;
  border-radius: 999px;
  padding: 0.15rem 0.55rem;
  font-size: 0.78rem;
  border: 1px solid transparent;
}
.status.in_stock { color: var(--ok); border-color: color-mix(in srgb, var(--ok), transparent 65%); }
.status.out_of_stock { color: var(--danger); border-color: color-mix(in srgb, var(--danger), transparent 65%); }
.buy-link {
  color: var(--accent);
  text-decoration: none;
  border: 1px solid color-mix(in srgb, var(--accent), transparent 70%);
  padding: 0.35rem 0.6rem;
  border-radius: 8px;
}
footer { margin-top: 1rem; color: var(--muted); }
@media (max-width: 760px) {
  th:nth-child(3), td:nth-child(3),
  th:nth-child(6), td:nth-child(6) { display: none; }
}
"""


APP_JS_TEMPLATE = """const dashboard = window.__DASHBOARD_DATA__;
let rows = [...dashboard.products];
let sortState = { key: "site", asc: true };

function renderStats() {
  const statsEl = document.getElementById("stats");
  const cards = [
    { label: "Total Products", value: dashboard.stats.total_products },
    { label: "In Stock", value: dashboard.stats.in_stock },
    { label: "Out of Stock", value: dashboard.stats.out_of_stock },
    { label: "Sites", value: dashboard.stats.total_sites }
  ];
  statsEl.innerHTML = cards.map((card) => `
    <article class="stat">
      <div class="label">${card.label}</div>
      <div class="value">${card.value}</div>
    </article>
  `).join("");
}

function sortRows(key) {
  if (sortState.key === key) {
    sortState.asc = !sortState.asc;
  } else {
    sortState.key = key;
    sortState.asc = true;
  }
  rows.sort((a, b) => {
    const av = String(a[key] ?? "");
    const bv = String(b[key] ?? "");
    return sortState.asc ? av.localeCompare(bv) : bv.localeCompare(av);
  });
  renderRows();
}

function renderRows() {
  const body = document.getElementById("products-body");
  body.innerHTML = rows.map((row) => `
    <tr>
      <td>${row.site}</td>
      <td title="${row.name_raw}">${row.name_en || row.name_raw || "-"}</td>
      <td>${row.platform}</td>
      <td><span class="status ${row.stock_status}">${row.stock_status}</span></td>
      <td>${row.price_raw || "-"}</td>
      <td>${row.last_seen_at || "-"}</td>
      <td><a class="buy-link" href="${row.canonical_url}" target="_blank" rel="noopener">Buy Now</a></td>
    </tr>
  `).join("");
}

function bindSorting() {
  document.querySelectorAll("th[data-sort]").forEach((th) => {
    th.addEventListener("click", () => sortRows(th.dataset.sort));
  });
}

function bindTheme() {
  const btn = document.getElementById("theme-toggle");
  btn.addEventListener("click", () => {
    const body = document.body;
    body.dataset.theme = body.dataset.theme === "dark" ? "light" : "dark";
  });
}

function renderUpdated() {
  document.getElementById("last-updated").textContent = `Last updated: ${dashboard.generated_at}`;
}

renderStats();
renderRows();
bindSorting();
bindTheme();
renderUpdated();
"""


def generate_dashboard(products_payload: dict[str, Any], output_dir: str = "web") -> None:
    logger = get_logger("dashboard_generator")
    out = Path(output_dir)
    assets = out / "assets"
    out.mkdir(parents=True, exist_ok=True)
    assets.mkdir(parents=True, exist_ok=True)

    products = list(products_payload.get("products", []))
    stats = dict(products_payload.get("stats", {}))
    stats["total_sites"] = len({item.get("site") for item in products if item.get("site")})
    generated_at = products_payload.get("generated_at") or datetime.now(timezone.utc).isoformat()

    data = {
        "generated_at": generated_at,
        "stats": stats,
        "products": products,
    }
    html = HTML_TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    (out / "index.html").write_text(html, encoding="utf-8")
    (assets / "style.css").write_text(CSS_TEMPLATE, encoding="utf-8")
    (assets / "app.js").write_text(APP_JS_TEMPLATE, encoding="utf-8")
    logger.info("dashboard generated path=%s products=%s", out / "index.html", len(products))

