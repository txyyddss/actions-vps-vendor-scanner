const dashboard = window.__DASHBOARD_DATA__;
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
