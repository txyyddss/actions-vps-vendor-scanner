# Module Guide

## Discoverer
- `src/discoverer/link_discoverer.py`
- Breadth-first URL discovery with same-domain guard and link heuristics.

## Hidden Scanners
- WHMCS:
  - `src/hidden_scanner/whmcs/gid_scanner.py`
  - `src/hidden_scanner/whmcs/pid_scanner.py`
- HostBill:
  - `src/hidden_scanner/hostbill/catid_scanner.py`
  - `src/hidden_scanner/hostbill/pid_scanner.py`

## Parsers
- `src/parsers/whmcs_parser.py`
- `src/parsers/hostbill_parser.py`

## Site-specific APIs
- `src/site_specific/acck_api.py`
- `src/site_specific/akile_api.py`

## Misc helpers
- `src/misc/http_client.py`
- `src/misc/flaresolverr_client.py`
- `src/misc/browser_client.py`
- `src/misc/retry_rate_limit.py`
- `src/misc/telegram_sender.py`
- `src/misc/dashboard_generator.py`

## Data and state
- `data/products.json`
- `data/stock.json`
- `data/state.json`
