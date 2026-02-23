# Testing

Run all tests:

```bash
pytest
```

Test coverage includes:
- URL normalization and URL washing
- Merge conflict priority behavior
- WHMCS parser in-stock/out-of-stock detection
- HostBill parser stock signal detection
- FlareSolverr client success/error paths
- Retry/rate-limit primitives
- Stock restock transition logic
- Issue processor form parsing and config mutation

Live-site smoke tests are intentionally excluded from CI by default.
