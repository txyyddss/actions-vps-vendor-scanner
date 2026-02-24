# Testing Strategy

Because live vendor sites often introduce unexpected Cloudflare challenges, temporary 502s, or dynamically changing HTML schemas, tests in this project isolate side-effects.

## Running Tests

From the repository root, run:
```bash
python -m pytest tests/
```

## What Is Covered

- **URL Normalization**: Ensuring `url_normalizer.py` correctly canonicalizes parameters, strips volatile tracking tags, and intelligently formats query paths for deterministic deduplication.
- **Parsers**: Feeding static HTML snapshots of out-of-stock, in-stock, and hidden WHMCS/HostBill pages to verify that the `ParsedItem` extracts data properly.
- **Merge Conflict Resolution**: Triggering the deduplication logic with intersecting URLs to ensure the correct item (`product_scanner` vs `discoverer` confidence) wins out.
- **Circuit Breakers**: Simulating repeated 403 or 503 failures to ensure the fetcher skips the domain on subsequent calls.

## Live Smoke Tests

Due to rate-limits and actions minutes, real external HTTP calls are turned off by default in CI runs. For local verification, you can run tests with specific sites or environments:

```bash
python -m src.main_scanner --mode discoverer --site "Specific Vendor"
```

## Continuous Integration

The GitHub Actions workflows continuously run the python test suite and standard linting phases. Submissions that cause regressions on the static parser logic will block Pull Requests from passing.
