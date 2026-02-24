const dashboard = window.__DASHBOARD_DATA__;
let rows = [...dashboard.products];
let sortState = { key: "site", asc: true };

function esc(str) {
  const el = document.createElement("span");
  el.textContent = str;
  return el.innerHTML;
}

function renderStats() {
  const statsEl = document.getElementById("stats");
  if (!dashboard.show_stats) { statsEl.style.display = "none"; return; }
  const cards = [
    { label: "Total Products", value: dashboard.stats.total_products },
    { label: "In Stock", value: dashboard.stats.in_stock },
    { label: "Out of Stock", value: dashboard.stats.out_of_stock },
    { label: "Sites", value: dashboard.stats.total_sites }
  ];
  statsEl.innerHTML = cards.map((card) => `
    <article class="stat">
      <div class="label">${esc(card.label)}</div>
      <div class="value">${esc(String(card.value))}</div>
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
      <td>${esc(row.site)}</td>
      <td title="${esc(row.name_raw)}">${esc(row.name_en || row.name_raw || "-")}</td>
      <td>${esc(row.platform)}</td>
      <td><span class="status ${esc(row.stock_status)}">${esc(row.stock_status)}</span></td>
      <td>${esc(row.price_raw || "-")}</td>
      <td>${esc(row.last_seen_at || "-")}</td>
      <td><a class="buy-link" href="${esc(row.canonical_url)}" target="_blank" rel="noopener">Buy Now</a></td>
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
