from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

import httpx

from src.misc.config_loader import dump_json, load_json, normalize_site_entry
from src.misc.logger import setup_logging
from src.misc.telegram_sender import TelegramSender


def _parse_markdown_form(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    current_key = ""
    buffer: list[str] = []
    for line in body.splitlines():
        if line.startswith("### "):
            if current_key:
                fields[current_key] = "\n".join(buffer).strip()
            current_key = line[4:].strip().lower().replace(" ", "_")
            buffer = []
        else:
            buffer.append(line)
    if current_key:
        fields[current_key] = "\n".join(buffer).strip()
    return fields


def _github_api(
    method: str,
    endpoint: str,
    token: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
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


def _validate_site_payload(fields: dict[str, str]) -> tuple[bool, str]:
    required = ("action", "site_name", "base_url")
    missing = [key for key in required if not fields.get(key)]
    if missing:
        return False, f"Missing required fields: {', '.join(missing)}"
    if fields["action"].strip().lower() not in {"add", "edit", "delete"}:
        return False, "Action must be add, edit, or delete."
    if not re.match(r"^https?://", fields["base_url"].strip()):
        return False, "Base URL must start with http:// or https://."
    return True, ""


def _apply_site_change(fields: dict[str, str], sites_path: str = "config/sites.json") -> tuple[bool, str]:
    payload = load_json(sites_path)
    sites = payload.setdefault("sites", {}).setdefault("site", [])
    action = fields["action"].strip().lower()
    name = fields["site_name"].strip()

    existing_idx = next((idx for idx, site in enumerate(sites) if str(site.get("name", "")).strip() == name), -1)
    if action == "delete":
        if existing_idx == -1:
            return False, f"Site '{name}' not found."
        sites.pop(existing_idx)
        dump_json(sites_path, payload)
        return True, f"Deleted site '{name}'."

    normalized = normalize_site_entry(
        {
            "enabled": fields.get("enabled", "true").strip().lower() != "false",
            "name": name,
            "url": fields["base_url"].strip(),
            "discoverer": fields.get("discoverer", "true").strip().lower() != "false",
            "category": fields.get("platform", fields.get("category", "")).strip() or "WHMCS",
            "special_crawler": fields.get("special_crawler", "").strip(),
            "product_scanner": fields.get("product_scanner", "true").strip().lower() != "false",
            "category_scanner": fields.get("category_scanner", "true").strip().lower() != "false",
            "scan_bounds": {},
        }
    )

    if existing_idx == -1 and action == "edit":
        return False, f"Cannot edit '{name}' because it does not exist."
    if existing_idx != -1 and action == "add":
        return False, f"Cannot add '{name}' because it already exists."

    if existing_idx == -1:
        sites.append(normalized)
        msg = f"Added site '{name}'."
    else:
        sites[existing_idx] = normalized
        msg = f"Updated site '{name}'."
    dump_json(sites_path, payload)
    return True, msg


def _comment_and_maybe_close(
    issue_number: int,
    message: str,
    close_invalid: bool,
) -> None:
    token = os.getenv("GITHUB_TOKEN", "")
    repo = os.getenv("GITHUB_REPOSITORY", "")
    if not token or not repo or issue_number <= 0:
        return
    base = f"https://api.github.com/repos/{repo}"
    _github_api("POST", f"{base}/issues/{issue_number}/comments", token, {"body": message})
    if close_invalid:
        _github_api(
            "PATCH",
            f"{base}/issues/{issue_number}",
            token,
            {"state": "closed", "state_reason": "not_planned"},
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issue-number", type=int, default=0)
    args = parser.parse_args()

    setup_logging()
    event_path = os.getenv("GITHUB_EVENT_PATH", "")
    if not event_path or not Path(event_path).exists():
        return

    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    issue = event.get("issue", {})
    issue_number = args.issue_number or int(issue.get("number", 0))
    title = str(issue.get("title", ""))
    body = str(issue.get("body", ""))
    labels = [str(label.get("name", "")).lower() for label in issue.get("labels", []) if isinstance(label, dict)]
    fields = _parse_markdown_form(body)
    telegram = TelegramSender(load_json("config/config.json").get("telegram", {}))

    is_site_change = "site" in title.lower() or "site_change" in fields or "site-change" in labels
    if is_site_change:
        ok, reason = _validate_site_payload(fields)
        if not ok:
            _comment_and_maybe_close(
                issue_number=issue_number,
                message=f"Issue form is invalid:\n\n- {reason}\n\nClosing as not planned.",
                close_invalid=True,
            )
            telegram.send_run_stats("Issue Processor", {"issue": issue_number, "status": "invalid", "reason": reason})
            return

        changed, message = _apply_site_change(fields, "config/sites.json")
        if not changed:
            _comment_and_maybe_close(
                issue_number=issue_number,
                message=f"Unable to process request:\n\n- {message}\n\nClosing as not planned.",
                close_invalid=True,
            )
            telegram.send_run_stats("Issue Processor", {"issue": issue_number, "status": "rejected", "reason": message})
            return

        _comment_and_maybe_close(
            issue_number=issue_number,
            message=f"Processed automatically:\n\n- {message}\n\nPlease verify the next scanner run.",
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

