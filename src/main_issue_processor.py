from __future__ import annotations
"""Processes GitHub issues to add, edit, or delete monitored sites automatically."""

import argparse
import copy
import json
import os
import re
from pathlib import Path
from typing import Any

import httpx

from src.hidden_scanner.hostbill.pid_scanner import scan_hostbill_pids
from src.hidden_scanner.whmcs.pid_scanner import scan_whmcs_pids
from src.misc.config_loader import dump_json, load_config, load_json, normalize_site_entry
from src.misc.http_client import HttpClient
from src.misc.logger import get_logger, setup_logging
from src.misc.telegram_sender import TelegramSender
from src.others.state_store import StateStore
from src.site_specific.acck_api import scan_acck_api
from src.site_specific.akile_api import scan_akile_api

TELEGRAM_CHANNEL_URL = "https://t.me/tx_stock_monitor"


def _parse_markdown_form(body: str) -> dict[str, str]:
    """Executes _parse_markdown_form logic."""
    fields: dict[str, str] = {}
    current_key = ""
    buffer: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.rstrip()
        if line.startswith("### "):
            if current_key:
                fields[current_key] = "\n".join(buffer).strip()
            current_key = line[4:].strip().lower().replace(" ", "_")
            buffer = []
            continue
        if line.startswith("<!--") and line.endswith("-->"):
            continue
        buffer.append(line)
    if current_key:
        fields[current_key] = "\n".join(buffer).strip()
    return fields


def _parse_positive_int(value: str) -> int | None:
    """Executes _parse_positive_int logic."""
    match = re.search(r"\d+", value or "")
    if not match:
        return None
    parsed = int(match.group(0))
    return parsed if parsed > 0 else None


def _parse_bool(value: str, default: bool = True) -> bool:
    """Executes _parse_bool logic."""
    normalized = str(value or "").strip().lower()
    if normalized in {"true", "yes", "1", "on"}:
        return True
    if normalized in {"false", "no", "0", "off"}:
        return False
    return default


def _validate_site_payload(fields: dict[str, str]) -> tuple[bool, str]:
    """Executes _validate_site_payload logic."""
    action = fields.get("action", "").strip().lower()
    if action not in {"add", "edit", "delete"}:
        return False, "Action must be add, edit, or delete."

    site_name = fields.get("site_name", "").strip()
    if not site_name:
        return False, "Site Name is required."

    if action in {"add", "edit"}:
        base_url = fields.get("base_url", "").strip()
        if not re.match(r"^https?://", base_url):
            return False, "Base URL must start with http:// or https://."
        platform = fields.get("platform", "").strip()
        if platform not in {"WHMCS", "HostBill", "SPECIAL"}:
            return False, "Platform must be WHMCS, HostBill, or SPECIAL."
        expected = _parse_positive_int(fields.get("expected_product_number", ""))
        if expected is None:
            return False, "Expected Product Number must be a positive integer."

    return True, ""


def _build_site_entry(fields: dict[str, str]) -> dict[str, Any]:
    """Executes _build_site_entry logic."""
    return normalize_site_entry(
        {
            "enabled": _parse_bool(fields.get("enabled", "true"), True),
            "name": fields.get("site_name", "").strip(),
            "url": fields.get("base_url", "").strip(),
            "discoverer": _parse_bool(fields.get("discoverer", "true"), True),
            "category": fields.get("platform", fields.get("category", "WHMCS")).strip() or "WHMCS",
            "special_crawler": fields.get("special_crawler", "").strip(),
            "product_scanner": _parse_bool(fields.get("product_scanner", "true"), True),
            "category_scanner": _parse_bool(fields.get("category_scanner", "true"), True),
            "scan_bounds": {},
        }
    )


def _github_api(
    method: str,
    endpoint: str,
    token: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Executes _github_api logic."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    with httpx.Client(timeout=20) as client:
        response = client.request(method, endpoint, json=payload, headers=headers)
        response.raise_for_status()
        if response.text:
            return response.json()
        return {}


def _comment_and_maybe_close(
    issue_number: int,
    message: str,
    close_invalid: bool,
) -> None:
    """Executes _comment_and_maybe_close logic."""
    token = os.getenv("GITHUB_TOKEN", "")
    repo = os.getenv("GITHUB_REPOSITORY", "")
    logger = get_logger("issue_processor")
    if not token or not repo or issue_number <= 0:
        return
    base = f"https://api.github.com/repos/{repo}"
    try:
        _github_api("POST", f"{base}/issues/{issue_number}/comments", token, {"body": message})
        if close_invalid:
            _github_api(
                "PATCH",
                f"{base}/issues/{issue_number}",
                token,
                {"state": "closed", "state_reason": "not_planned"},
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to update issue %s: %s", issue_number, exc)


def _build_validation_config(config: dict[str, Any], expected: int) -> dict[str, Any]:
    """Executes _build_validation_config logic."""
    test_config = copy.deepcopy(config)
    scanner_cfg = test_config.setdefault("scanner", {})
    defaults = scanner_cfg.setdefault("default_scan_bounds", {})

    # Expand scan window for validation and allow reaching expected thresholds.
    scanner_cfg["initial_scan_floor"] = max(int(scanner_cfg.get("initial_scan_floor", 80)), expected * 4)
    scanner_cfg["stop_tail_window"] = max(int(scanner_cfg.get("stop_tail_window", 60)), expected * 2)

    defaults["whmcs_pid_max"] = max(int(defaults.get("whmcs_pid_max", 2000)), expected * 10)
    defaults["hostbill_pid_max"] = max(int(defaults.get("hostbill_pid_max", 2500)), expected * 10)
    return test_config


def _run_site_product_count_test(site_entry: dict[str, Any], expected: int, config: dict[str, Any]) -> tuple[int, str]:
    """Executes _run_site_product_count_test logic."""
    test_config = _build_validation_config(config, expected)
    http_client = HttpClient(test_config)
    temp_state = StateStore(Path("data/tmp/issue_validation_state.json"))
    category = str(site_entry.get("category", "")).lower()
    special = str(site_entry.get("special_crawler", "")).lower()

    if special == "acck_api":
        records = scan_acck_api(site_entry, http_client)
        return len({record.get("canonical_url") for record in records}), "acck_api"
    if special == "akile_api":
        records = scan_akile_api(site_entry, http_client)
        return len({record.get("canonical_url") for record in records}), "akile_api"
    if category == "whmcs":
        records = scan_whmcs_pids(site_entry, test_config, http_client, temp_state)
        return len({record.get("canonical_url") for record in records}), "whmcs_pid_scan"
    if category == "hostbill":
        records = scan_hostbill_pids(site_entry, test_config, http_client, temp_state)
        return len({record.get("canonical_url") for record in records}), "hostbill_pid_scan"

    return 0, "unsupported-category"


def _apply_site_change(action: str, site_name: str, new_site: dict[str, Any], sites_path: str = "config/sites.json") -> tuple[bool, str]:
    """Executes _apply_site_change logic."""
    payload = load_json(sites_path)
    sites = payload.setdefault("sites", {}).setdefault("site", [])
    existing_idx = next((idx for idx, site in enumerate(sites) if str(site.get("name", "")).strip() == site_name), -1)

    if action == "delete":
        if existing_idx == -1:
            return False, f"Site '{site_name}' not found."
        sites.pop(existing_idx)
        dump_json(sites_path, payload)
        return True, f"Deleted site '{site_name}'."

    if existing_idx == -1 and action == "edit":
        return False, f"Cannot edit '{site_name}' because it does not exist."
    if existing_idx != -1 and action == "add":
        return False, f"Cannot add '{site_name}' because it already exists."

    if existing_idx == -1:
        sites.append(new_site)
        message = f"Added site '{site_name}'."
    else:
        sites[existing_idx] = new_site
        message = f"Updated site '{site_name}'."
    dump_json(sites_path, payload)
    return True, message


def main() -> None:
    """Executes main logic."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--issue-number", type=int, default=0)
    args = parser.parse_args()

    config = load_config("config/config.json")
    setup_logging(
        level=str(config.get("logging", {}).get("level", "INFO")),
        json_logs=bool(config.get("logging", {}).get("json_logs", False)),
    )

    event_path = os.getenv("GITHUB_EVENT_PATH", "")
    if not event_path or not Path(event_path).exists():
        return

    event = json.loads(Path(event_path).read_text(encoding="utf-8-sig"))
    issue = event.get("issue", {})
    issue_number = args.issue_number or int(issue.get("number", 0))
    title = str(issue.get("title", ""))
    body = str(issue.get("body", ""))
    labels = [str(label.get("name", "")).lower() for label in issue.get("labels", []) if isinstance(label, dict)]
    fields = _parse_markdown_form(body)
    telegram = TelegramSender(config.get("telegram", {}))

    action_hint = fields.get("action", "").strip().lower()
    is_site_change = "site-change" in labels or action_hint in {"add", "edit", "delete"} or "[site change]" in title.lower()
    if is_site_change:
        ok, reason = _validate_site_payload(fields)
        if not ok:
            _comment_and_maybe_close(
                issue_number=issue_number,
                message=(
                    f"Issue form is invalid:\n\n- {reason}\n\n"
                    f"Closing as not planned.\n\nTelegram channel: {TELEGRAM_CHANNEL_URL}"
                ),
                close_invalid=True,
            )
            telegram.send_run_stats("Issue Processor", {"issue": issue_number, "status": "invalid", "reason": reason})
            return

        action = fields.get("action", "").strip().lower()
        site_name = fields.get("site_name", "").strip()
        new_site = _build_site_entry(fields)

        if action in {"add", "edit"}:
            expected = _parse_positive_int(fields.get("expected_product_number", "")) or 0
            scanned_count, method = _run_site_product_count_test(new_site, expected, config)
            if scanned_count < expected:
                rejection = (
                    "Site request rejected by automatic validation.\n\n"
                    f"- Expected Product Number: {expected}\n"
                    f"- Scanned Product Number: {scanned_count}\n"
                    f"- Validation Method: {method}\n\n"
                    "The site was **not** added/updated. Please verify URL/platform/expectation and submit again.\n\n"
                    f"Telegram channel: {TELEGRAM_CHANNEL_URL}"
                )
                _comment_and_maybe_close(issue_number=issue_number, message=rejection, close_invalid=False)
                telegram.send_run_stats(
                    "Issue Processor",
                    {
                        "issue": issue_number,
                        "status": "rejected",
                        "expected_product_number": expected,
                        "scanned_product_number": scanned_count,
                        "validation_method": method,
                    },
                )
                return

        changed, message = _apply_site_change(action, site_name, new_site, "config/sites.json")
        if not changed:
            _comment_and_maybe_close(
                issue_number=issue_number,
                message=(
                    f"Unable to process request:\n\n- {message}\n\n"
                    f"Closing as not planned.\n\nTelegram channel: {TELEGRAM_CHANNEL_URL}"
                ),
                close_invalid=True,
            )
            telegram.send_run_stats("Issue Processor", {"issue": issue_number, "status": "rejected", "reason": message})
            return

        _comment_and_maybe_close(
            issue_number=issue_number,
            message=(
                f"Processed automatically:\n\n- {message}\n\n"
                f"Please verify the next scanner run.\n\nTelegram channel: {TELEGRAM_CHANNEL_URL}"
            ),
            close_invalid=False,
        )
        telegram.send_run_stats("Issue Processor", {"issue": issue_number, "status": "applied", "message": message})
        return

    # Feature/Bug issues -> notify only.
    telegram.send_run_stats(
        "Issue Notification",
        {
            "issue": issue_number,
            "title": title,
            "labels": ", ".join(labels),
        },
    )


if __name__ == "__main__":
    main()
