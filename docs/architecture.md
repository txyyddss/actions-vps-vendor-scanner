# Architecture

This project monitors VPS products and stock status using a multi-stage scanner pipeline.

## Key components

- `src/main_scanner.py`: orchestrates discoverer/category/product scans and merge output.
- `src/main_stock_alert.py`: checks existing product URLs and reports restocks.
- `src/main_issue_processor.py`: handles issue form automation for site changes.
- `src/misc/http_client.py`: tiered networking (direct HTTP, FlareSolverr, Playwright fallback).
- `src/others/data_merge.py`: conflict-priority merge and diff logic.
- `src/misc/dashboard_generator.py`: static cyberpunk dashboard builder.

## Data flow

1. Scanner jobs discover category/product candidates.
2. Product/category records are merged with source priority.
3. `data/products.json` and `web/` are regenerated.
4. Stock workflow checks product URLs and updates `data/stock.json`.

## Reliability controls

- Retries with exponential backoff.
- Per-domain rate limiting and cooldowns.
- Circuit breaker for repeated domain failures.
- Explicit stock evidence captured in each record.
