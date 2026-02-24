# Actions VPS Vendor Scanner

A highly resilient, automated product scanner and stock monitor for VPS vendors, specifically designed to handle WHMCS, HostBill, and custom API-driven sites. This project is intended to be run via GitHub Actions, providing frequent stock check updates and newly discovered plan alerts via Telegram.

## Key Features

- **Multi-Stage Scanning Pipeline**: Separates the crawling into multiple stages (Discoverer, Category Scanner, Product Scanner, and Merger) to allow efficient parallelization and debugging.
- **Adaptive Hidden Product Discovery**: Implements intelligent boundary-based ID enumeration (gids, pids, cat_ids) to discover hidden plans and categories, automatically storing highwater marks to reduce future scan times.
- **Tiered Evasion Network Stack**: Uses a multi-layered fetch approach: First HTTPX direct fetch, with a fallback to FlareSolverr for advanced JS challenges and anti-bot mitigations.
- **Robust Anti-Flap Data Merging**: Prioritizes stock status and data fidelity intelligently via a conflict-resolution merge system based on `source_priority`. Retains semantic keys (prices, cycles, locations, English/Raw names) cleanly.
- **Circuit Breakers & Rate Limits**: Ensures the crawler acts like a good citizen, throttling requests natively and cutting off unresponsive domains before they exhaust action minutes.
- **Actionable Telegram Alerts**: Chunked, detailed notifications highlighting exactly what changed since the last stock run, with Telegram-friendly formatting.
- **Static Dashboard Output**: Emits a beautifully crafted, static HTML+JS dashboard showing live inventory, which can be effortlessly hosted on GitHub Pages.
- **Automated Issue Processing**: Allows community members or operators to seamlessly add, remove, or modify site targets by simply filing specialized GitHub Issues. No manual JSON editing required.

## Getting Started

### Prerequisites

You need Python 3.9+ to effectively run the scripts. We strongly recommend using a virtual environment.

```bash
python -m venv venv
# Linux/macOS
source venv/bin/activate
# Windows
.\venv\Scripts\activate

python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Configuration Files

- `config/config.json`: Contains engine settings, API urls, rate limit bounds, crawler limits, and log configurations.
- `config/sites.json`: Source of truth for all monitored vendor sites. Contains URLs, category, and enabled capabilities for each.

### Running the Pipeline Locally

The tool supports a module-based execution which closely mimics the GitHub Actions pipeline:

```bash
# 1. Broadly discover product pages via BFS crawling
python -m src.main_scanner --mode discoverer

# 2. Iterate dynamically generated category IDs
python -m src.main_scanner --mode category

# 3. Aggressively enumerate product IDs based on historical highwater marks
python -m src.main_scanner --mode product

# 4. Filter, compile, and wash discovered lists down to a single master file
python -m src.main_scanner --mode merge
```

Or you can trigger the entire end-to-end operation with a single argument:
```bash
python -m src.main_scanner --mode all
```

To frequently poll for active restocks in existing high-priority products without rediscovering:
```bash
python -m src.main_stock_alert
```

To update the `web/index.html` static site data dynamically:
```bash
python -m src.main_dashboard
```

To test issue-based additions visually:
```bash
# Provide a stubbed Payload to your environment to see it tested
python -m src.main_issue_processor --issue-number 123
```

### GitHub Variables & Secrets

For a full cloud deployment, set up the following secrets in your GitHub repository:
- `TELEGRAM_BOT_TOKEN`: Your API token generated via BotFather.
- `TELEGRAM_CHAT_ID`: The recipient channel or chat.
- `TELEGRAM_TOPIC_ID`: Optional thread ID for forum-structured telegram groups.

Subscribe to real-time events via our community channel: [TX Stock Monitor](https://t.me/tx_stock_monitor)

## Development & Testing

Run all unit tests to validate schema regressions, HTTP behavior, and config sanity. Since live-site scraping inherently breaks logic due to 403s/timeouts, tests are typically mocked.

```bash
pytest
```

## Directory Structure
- `src/`: Core Python modules for crawlers, parsers, scanners, and helpers.
- `config/`: Configuration parameters and site manifest.
- `data/`: Ephemeral output products and historical tracking files (`products.json`, `stock.json`, `state.json`).
- `docs/`: Technical and API documentation.
- `tests/`: Automated test cases ensuring regressions do not persist into mainline.
- `web/`: Contains static dashboard template assets for final build consumption.

## Usage Caution

Use responsibly. Aggressive crawling can lead to IP bans or disruptions for smaller vendors. By default, `config.json` enforces fair use limits but always verify your specific environment logic.
