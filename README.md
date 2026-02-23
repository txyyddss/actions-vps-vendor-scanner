# actions-vps-vendor-scanner

GitHub Actions powered product scanner and stock monitor for WHMCS, HostBill, and special API vendors.

## Features

- Parallel scanner jobs (discoverer, category scanner, product scanner)
- Merge + washing pipeline with URL-key conflict priority
- Stock alert job every 15 minutes
- FlareSolverr + socks5 proxy + Playwright fallback chain
- Rate-limit safe retries and per-domain cooldowns
- Telegram alerts for product diff and restocks
- Static cyberpunk dashboard generation (`web/`)
- Automatic issue form processing for site add/edit/delete
- Pull request processor with tests and validation comment (no auto-approval)

## Quick start

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Edit config files:

- `config/config.json`
- `config/sites.json`

Run scanner stages locally:

```bash
python -m src.main_scanner --mode discoverer
python -m src.main_scanner --mode category
python -m src.main_scanner --mode product
python -m src.main_scanner --mode merge
```

Or run end-to-end:

```bash
python -m src.main_scanner --mode all
```

Run stock alert:

```bash
python -m src.main_stock_alert
```

Run dashboard generation:

```bash
python -m src.main_dashboard
```

Run issue processor locally (with event payload env):

```bash
python -m src.main_issue_processor --issue-number 123
```

GitHub repository secrets required for Telegram:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TELEGRAM_TOPIC_ID` (optional)

Run tests:

```bash
pytest
```

## Output files

- Product catalog: `data/products.json`
- Stock snapshot: `data/stock.json`
- Learned scan state: `data/state.json`
- Static dashboard: `web/index.html`

## GitHub workflows

- `.github/workflows/scanner.yml`
- `.github/workflows/stock-alert.yml`
- `.github/workflows/issue-processor.yml`
- `.github/workflows/pr-processor.yml`

## Notes

- Scanner keeps both raw and English-normalized fields.
- URLs are normalized and washed before persistence.
- Playwright fallback is lazy and only used when needed.
- Site add/edit issue requests require `Expected Product Number`; processor runs a live scan and rejects the request if scanned products are below that threshold.
