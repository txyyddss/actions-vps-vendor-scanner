# Modules Reference

A detailed guide on the internal Python modules and their responsibilities.

## `src.main_scanner`
The entrypoint for the main crawling routines. Routes execution to one of the four key stages (discoverer, category, product, or merge). The merge stage is also the primary stock-finalization step, resolving only unknown product states before it writes `products.json`, `stock.json`, and dashboard output.

## `src.main_stock_alert`
A lightweight, high-frequency follow-up job meant to be run between full scanner passes. Unlike the merge stage, it rechecks every known product row, refreshes `stock.json`, and emits any resulting stock change alerts.

## `src.main_issue_processor`
Handles automated interaction with GitHub Issues. Validates URLs and payload sanity before conditionally appending or updating the `sites.json` config manifest.

## Hidden Scanners
Responsible for probing sequentially incrementing numerical IDs to find non-public products and groups before they are officially indexed or linked on the vendor's homepage.
- **WHMCS**: `src.hidden_scanner.whmcs.*`
- **HostBill**: `src.hidden_scanner.hostbill.*`

## Data Handlers & Parsers
- `src.others.data_merge`: Ingests various lists, standardizes their structure, and gracefully resolves duplicates using a source confidence hierarchy.
- `src.parsers.whmcs_parser` & `src.parsers.hostbill_parser`: Transforms HTML payloads into structured `ParsedItem` dataclasses containing names, cycles, locations, and precise stock status rules.

## HTTP & Misc
- `src.misc.http_client`: The central `HttpClient` orchestrating retries, backoffs, and flaresolverr configuration.
- `src.misc.telegram_sender`: Safe chunked sender for Telegram messages guaranteeing limits are respected.
