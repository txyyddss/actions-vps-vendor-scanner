from __future__ import annotations

import argparse

from src.misc.config_loader import load_config
from src.misc.http_client import HttpClient
from src.parsers.hostbill_parser import parse_hostbill_page
from src.parsers.whmcs_parser import parse_whmcs_page


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url", help="URL to probe")
    parser.add_argument("--platform", default="WHMCS", choices=["WHMCS", "HostBill"])
    args = parser.parse_args()

    client = HttpClient(load_config("config/config.json"))
    result = client.get(args.url, force_english=True)
    print("tier=", result.tier, "status=", result.status_code, "final=", result.final_url)
    if not result.ok:
        print("error=", result.error)
        return

    if args.platform == "WHMCS":
        parsed = parse_whmcs_page(result.text, result.final_url)
    else:
        parsed = parse_hostbill_page(result.text, result.final_url)
    print("name=", parsed.name_raw)
    print("stock=", parsed.in_stock)
    print("evidence=", parsed.evidence)


if __name__ == "__main__":
    main()
