from __future__ import annotations
"""Templates and outputs the static asset files for the web dashboard."""

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
  <title>__TITLE__</title>
  <meta name="description" content="Live VPS inventory dashboard from WHMCS, HostBill, and API-driven vendors. Track stock, prices, and availability in real time.">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="assets/style.css">
</head>
<body data-theme="__THEME__">
  <div class="grid-bg"></div>
  <main class="page">
    <header class="hero">
      <div>
        <h1 id="page-title">__TITLE__</h1>
        <p>Live VPS inventory from WHMCS, HostBill, and API-driven vendors.</p>
      </div>
      <div class="hero-actions">
        <a class="hero-link" href="https://t.me/tx_stock_monitor" target="_blank" rel="noopener">📢 Telegram</a>
        <button id="theme-toggle" title="Toggle theme">🌓</button>
      </div>
    </header>
    <section class="stats" id="stats"></section>
    <section class="controls">
      <input type="text" id="search-input" placeholder="Search products..." autocomplete="off">
      <select id="site-filter"><option value="">All Sites</option></select>
      <select id="stock-filter">
        <option value="">All Status</option>
        <option value="1">🟢 In Stock</option>
        <option value="0">🔴 Out of Stock</option>
        <option value="-1">⚪ Unknown</option>
      </select>
      <span id="result-count" class="result-count"></span>
    </section>
    <section class="table-wrap">
      <table id="products-table">
        <thead>
          <tr>
            <th data-sort="site">Site</th>
            <th data-sort="name_raw">Product</th>
            <th data-sort="platform">Platform</th>
            <th data-sort="in_stock">Status</th>
            <th data-sort="price_raw">Price</th>
            <th data-sort="last_seen_at">Updated</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody id="products-body"></tbody>
      </table>
    </section>
    <footer>
      <small id="last-updated"></small>
      <small><a class="footer-link" href="https://t.me/tx_stock_monitor" target="_blank" rel="noopener">https://t.me/tx_stock_monitor</a></small>
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
  --bg-elev2: #1a2436;
  --line: #1f2c43;
  --text: #d3e4ff;
  --muted: #89a4d1;
  --accent: #03f5c4;
  --accent-dim: rgba(3,245,196,0.12);
  --danger: #ff4d6d;
  --ok: #1ce870;
  --warn: #ffb347;
  --radius: 12px;
}
body[data-theme="light"] {
  --bg: #eef3fc;
  --bg-elev: #ffffff;
  --bg-elev2: #f5f7fb;
  --line: #cfd8ea;
  --text: #14233d;
  --muted: #5e6e8e;
  --accent: #007ea7;
  --accent-dim: rgba(0,126,167,0.08);
  --danger: #b3002d;
  --ok: #087f37;
  --warn: #b87300;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  min-height: 100vh;
  font-family: "Inter", "Segoe UI", sans-serif;
  background: radial-gradient(circle at top right, var(--accent-dim), transparent 42%), var(--bg);
  color: var(--text);
  line-height: 1.5;
}
.grid-bg {
  position: fixed; inset: 0;
  background-image:
    linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px);
  background-size: 24px 24px;
  pointer-events: none;
}
.page { max-width: 1280px; margin: 0 auto; padding: 1.2rem; }

/* Hero */
.hero {
  display: flex; justify-content: space-between; gap: 1rem; align-items: center;
  background: var(--bg-elev);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 1.2rem 1.5rem;
}
.hero h1 { margin-bottom: 0.3rem; font-size: clamp(1.3rem, 3vw, 1.8rem); font-weight: 700; }
.hero p { color: var(--muted); font-size: 0.9rem; }
.hero-actions { display: flex; gap: 0.5rem; align-items: center; }
button, .hero-link {
  border: 1px solid var(--line);
  background: transparent;
  color: var(--text);
  padding: 0.5rem 0.8rem;
  border-radius: 8px;
  cursor: pointer;
  font-size: 0.85rem;
  transition: border-color 0.2s, background 0.2s;
}
button:hover, .hero-link:hover {
  border-color: var(--accent);
  background: var(--accent-dim);
}
.hero-link {
  color: var(--accent);
  text-decoration: none;
}

/* Stats */
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 0.7rem;
  margin-top: 0.9rem;
}
.stat {
  background: var(--bg-elev);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 0.9rem 1rem;
  transition: transform 0.2s, border-color 0.2s;
}
.stat:hover {
  transform: translateY(-2px);
  border-color: var(--accent);
}
.stat .label { color: var(--muted); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.04em; }
.stat .value { font-size: 1.5rem; font-weight: 700; margin-top: 0.15rem; }
.stat.in-stock .value { color: var(--ok); }
.stat.out-of-stock .value { color: var(--danger); }
.stat.unknown .value { color: var(--warn); }

/* Controls */
.controls {
  display: flex; flex-wrap: wrap; gap: 0.6rem; align-items: center;
  margin-top: 0.9rem;
}
#search-input {
  flex: 1 1 200px;
  min-width: 180px;
  background: var(--bg-elev);
  border: 1px solid var(--line);
  color: var(--text);
  padding: 0.6rem 1rem;
  border-radius: 8px;
  font-size: 0.88rem;
  outline: none;
  transition: border-color 0.2s;
}
#search-input:focus { border-color: var(--accent); }
#search-input::placeholder { color: var(--muted); }
select {
  background: var(--bg-elev);
  border: 1px solid var(--line);
  color: var(--text);
  padding: 0.6rem 0.8rem;
  border-radius: 8px;
  font-size: 0.85rem;
  cursor: pointer;
  outline: none;
}
.result-count { color: var(--muted); font-size: 0.8rem; margin-left: auto; }

/* Table */
.table-wrap {
  margin-top: 0.9rem;
  overflow-x: auto;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--bg-elev);
}
table { width: 100%; border-collapse: collapse; }
th, td {
  text-align: left;
  padding: 0.65rem 0.8rem;
  border-bottom: 1px solid var(--line);
  font-size: 0.85rem;
  white-space: nowrap;
}
th {
  color: var(--muted); cursor: pointer; user-select: none;
  font-weight: 600; font-size: 0.78rem; text-transform: uppercase;
  letter-spacing: 0.03em;
  position: sticky; top: 0; background: var(--bg-elev);
}
th:hover { color: var(--accent); }
th.sorted-asc::after { content: " ↑"; }
th.sorted-desc::after { content: " ↓"; }
td.name-cell { white-space: normal; max-width: 280px; }
tr:hover { background: var(--bg-elev2); }

/* Status badges */
.badge {
  display: inline-flex; align-items: center; gap: 0.3rem;
  border-radius: 999px;
  padding: 0.15rem 0.6rem;
  font-size: 0.75rem;
  font-weight: 600;
  border: 1px solid transparent;
}
.badge.in-stock { color: var(--ok); border-color: color-mix(in srgb, var(--ok), transparent 60%); background: color-mix(in srgb, var(--ok), transparent 92%); }
.badge.oos { color: var(--danger); border-color: color-mix(in srgb, var(--danger), transparent 60%); background: color-mix(in srgb, var(--danger), transparent 92%); }
.badge.unknown { color: var(--warn); border-color: color-mix(in srgb, var(--warn), transparent 60%); background: color-mix(in srgb, var(--warn), transparent 92%); }

/* Action button */
.buy-link {
  color: var(--accent);
  text-decoration: none;
  border: 1px solid color-mix(in srgb, var(--accent), transparent 60%);
  padding: 0.3rem 0.6rem;
  border-radius: 6px;
  font-size: 0.78rem;
  font-weight: 500;
  transition: background 0.2s;
}
.buy-link:hover { background: var(--accent-dim); }

/* DESC tooltip */
.desc-tooltip {
  position: relative;
  cursor: help;
}
.desc-tooltip .desc-text {
  display: none;
  position: absolute;
  left: 0; top: 100%;
  background: var(--bg-elev2);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 0.6rem 0.8rem;
  font-size: 0.78rem;
  white-space: pre-wrap;
  max-width: 320px;
  max-height: 200px;
  overflow-y: auto;
  z-index: 10;
  color: var(--text);
  box-shadow: 0 4px 16px rgba(0,0,0,0.3);
}
.desc-tooltip:hover .desc-text { display: block; }

footer {
  margin-top: 1rem;
  color: var(--muted);
  display: flex;
  justify-content: space-between;
  gap: 0.8rem;
  flex-wrap: wrap;
  font-size: 0.8rem;
}
.footer-link { color: var(--accent); text-decoration: none; }

@media (max-width: 768px) {
  .hero { flex-direction: column; align-items: flex-start; }
  th:nth-child(3), td:nth-child(3),
  th:nth-child(6), td:nth-child(6) { display: none; }
  .controls { flex-direction: column; }
  #search-input { flex: none; width: 100%; }
  .result-count { margin-left: 0; }
}
"""


APP_JS_TEMPLATE = """const dashboard = window.__DASHBOARD_DATA__;
let allRows = [...dashboard.products];
let filteredRows = allRows;
let sortState = { key: "site", asc: true };

function esc(str) {
  const el = document.createElement("span");
  el.textContent = str || "";
  return el.innerHTML;
}

function stockBadge(val) {
  if (val === 1) return '<span class="badge in-stock">🟢 In Stock</span>';
  if (val === 0) return '<span class="badge oos">🔴 Out of Stock</span>';
  return '<span class="badge unknown">⚪ Unknown</span>';
}

function timeSince(iso) {
  if (!iso) return "-";
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 60) return m + "m ago";
  const h = Math.floor(m / 60);
  if (h < 24) return h + "h ago";
  return Math.floor(h / 24) + "d ago";
}

function renderStats() {
  const el = document.getElementById("stats");
  if (!dashboard.show_stats) { el.style.display = "none"; return; }
  const s = dashboard.stats;
  const cards = [
    { label: "Total Products", value: s.total_products, cls: "" },
    { label: "In Stock", value: s.in_stock, cls: "in-stock" },
    { label: "Out of Stock", value: s.out_of_stock, cls: "out-of-stock" },
    { label: "Unknown", value: s.unknown ?? (s.total_products - s.in_stock - s.out_of_stock), cls: "unknown" },
    { label: "Sites", value: dashboard.stats.total_sites, cls: "" },
  ];
  el.innerHTML = cards.map(c => `
    <article class="stat ${c.cls}">
      <div class="label">${esc(c.label)}</div>
      <div class="value">${esc(String(c.value ?? 0))}</div>
    </article>
  `).join("");
}

function populateSiteFilter() {
  const sites = [...new Set(allRows.map(r => r.site).filter(Boolean))].sort();
  const select = document.getElementById("site-filter");
  sites.forEach(s => {
    const opt = document.createElement("option");
    opt.value = s;
    opt.textContent = s;
    select.appendChild(opt);
  });
}

function applyFilters() {
  const q = document.getElementById("search-input").value.toLowerCase();
  const site = document.getElementById("site-filter").value;
  const stock = document.getElementById("stock-filter").value;
  filteredRows = allRows.filter(r => {
    if (site && r.site !== site) return false;
    if (stock !== "" && String(r.in_stock) !== stock) return false;
    if (q) {
      const haystack = [r.site, r.name_raw, r.platform, r.canonical_url, r.description_raw, r.price_raw]
        .filter(Boolean).join(" ").toLowerCase();
      if (!haystack.includes(q)) return false;
    }
    return true;
  });
  applySorting();
  renderRows();
  document.getElementById("result-count").textContent =
    filteredRows.length === allRows.length ? "" : `${filteredRows.length} / ${allRows.length}`;
}

function applySorting() {
  const { key, asc } = sortState;
  filteredRows.sort((a, b) => {
    let av = a[key] ?? "";
    let bv = b[key] ?? "";
    if (typeof av === "number" && typeof bv === "number") return asc ? av - bv : bv - av;
    av = String(av); bv = String(bv);
    return asc ? av.localeCompare(bv) : bv.localeCompare(av);
  });
}

function sortRows(key) {
  if (sortState.key === key) {
    sortState.asc = !sortState.asc;
  } else {
    sortState.key = key;
    sortState.asc = true;
  }
  document.querySelectorAll("th[data-sort]").forEach(th => {
    th.classList.remove("sorted-asc", "sorted-desc");
    if (th.dataset.sort === key) {
      th.classList.add(sortState.asc ? "sorted-asc" : "sorted-desc");
    }
  });
  applySorting();
  renderRows();
}

function renderRows() {
  const body = document.getElementById("products-body");
  body.innerHTML = filteredRows.map(r => {
    const name = esc(r.name_raw || "-");
    const hasDesc = r.description_raw && r.description_raw.length > 5;
    const nameCell = hasDesc
      ? `<span class="desc-tooltip">${name}<span class="desc-text">${esc(r.description_raw.substring(0, 500))}</span></span>`
      : name;
    return `<tr>
      <td>${esc(r.site)}</td>
      <td class="name-cell">${nameCell}</td>
      <td>${esc(r.platform)}</td>
      <td>${stockBadge(r.in_stock)}</td>
      <td>${esc(r.price_raw || "-")}</td>
      <td title="${esc(r.last_seen_at || "")}">${timeSince(r.last_seen_at)}</td>
      <td><a class="buy-link" href="${esc(r.canonical_url)}" target="_blank" rel="noopener">View →</a></td>
    </tr>`;
  }).join("");
}

function bindControls() {
  document.querySelectorAll("th[data-sort]").forEach(th => {
    th.addEventListener("click", () => sortRows(th.dataset.sort));
  });
  document.getElementById("search-input").addEventListener("input", applyFilters);
  document.getElementById("site-filter").addEventListener("change", applyFilters);
  document.getElementById("stock-filter").addEventListener("change", applyFilters);
  document.getElementById("theme-toggle").addEventListener("click", () => {
    const body = document.body;
    body.dataset.theme = body.dataset.theme === "dark" ? "light" : "dark";
    localStorage.setItem("theme", body.dataset.theme);
  });
  // Restore theme
  const saved = localStorage.getItem("theme");
  if (saved) document.body.dataset.theme = saved;
}

function renderUpdated() {
  const el = document.getElementById("last-updated");
  if (dashboard.generated_at) {
    el.textContent = `Last updated: ${timeSince(dashboard.generated_at)} (${new Date(dashboard.generated_at).toLocaleString()})`;
  }
}

renderStats();
populateSiteFilter();
applyFilters();
bindControls();
renderUpdated();
"""


def generate_dashboard(
    products_payload: dict[str, Any],
    output_dir: str = "web",
    dashboard_cfg: dict[str, Any] | None = None,
) -> None:
    """Generate the static HTML dashboard from product data."""
    logger = get_logger("dashboard_generator")
    cfg = dashboard_cfg or {}
    out = Path(output_dir)
    assets = out / "assets"
    out.mkdir(parents=True, exist_ok=True)
    assets.mkdir(parents=True, exist_ok=True)

    title = str(cfg.get("title", "VPS Inventory Dashboard"))
    theme = str(cfg.get("default_theme", "dark"))
    show_stats = bool(cfg.get("show_stats", True))

    # Flatten site-grouped format into flat product list for JS frontend
    sites = products_payload.get("sites")
    if isinstance(sites, list):
        products: list[dict[str, Any]] = []
        for site_block in sites:
            site_name = site_block.get("site", "")
            platform = site_block.get("platform", "")
            for item in site_block.get("products", []):
                products.append({**item, "site": site_name, "platform": platform})
            for item in site_block.get("categories", []):
                products.append({**item, "site": site_name, "platform": platform})
        total_sites = len(sites)
    else:
        # Legacy flat format fallback
        products = list(products_payload.get("products", []))
        total_sites = len({item.get("site") for item in products if item.get("site")})

    stats = dict(products_payload.get("stats", {}))
    stats["total_sites"] = total_sites
    generated_at = products_payload.get("generated_at") or datetime.now(timezone.utc).isoformat()

    data = {
        "generated_at": generated_at,
        "stats": stats,
        "show_stats": show_stats,
        "products": products,
    }
    raw_json = json.dumps(data, ensure_ascii=False)
    safe_json = raw_json.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    html = HTML_TEMPLATE.replace("__DATA__", safe_json)
    html = html.replace("__TITLE__", title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    html = html.replace("__THEME__", theme if theme in {"dark", "light"} else "dark")
    (out / "index.html").write_text(html, encoding="utf-8")
    (assets / "style.css").write_text(CSS_TEMPLATE, encoding="utf-8")
    (assets / "app.js").write_text(APP_JS_TEMPLATE, encoding="utf-8")
    logger.info("dashboard generated path=%s products=%s", out / "index.html", len(products))
