# Scanner Architecture

This project is built around a multi-stage scanner pipeline designed to scale across dozens of VPS vendors safely and reliably.

## Overall Pipeline

1. **Discovery Stage (`main_scanner.py --mode discoverer`)**
   - Initiates a BFS (Breadth-First Search) URL crawler on enabled sites.
   - Respects depth and page limits per site to avoid being trapped in infinite loops.
   - Extracts product and category links to pass to the next stages.

2. **Category / Group Scan (`main_scanner.py --mode category`)**
   - Scans incrementally for category IDs in WHMCS (`gid=...`) and HostBill (`cat_id=...`).
   - Learns and saves highwater marks so future runs resume from near the last known ID.

3. **Product Scan (`main_scanner.py --mode product`)**
   - Scans incrementally for product IDs.
   - Applies similar adaptive limits driven by `AdaptiveScanController` to reduce time spent on inactive ranges.

4. **Data Merging (`main_scanner.py --mode merge`)**
   - Combines output from all stages.
   - Prioritizes higher-quality parses (e.g. `product_scanner` outputs > `discoverer` outputs).
   - Resolves conflicts, retains semantic English names, and generates final static `products.json` file.

## Resilience and Bot Evasion

- **Circuit Breaker**: Repeated 500s or timeouts open the circuit, preventing the scanner from hammering a broken vendor.
- **Rate Limiting**: Configured to respect global QPS limits and per-domain limits.
- **Tiered Fetching**: Starts with plain HTTPX, and falls back to `FlareSolverr` for basic Cloudflare intercepts and advanced JS challenges.
