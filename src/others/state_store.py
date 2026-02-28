"""Persists scanner progress (highwater marks) across stateless GitHub Action runs."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.misc.config_loader import dump_json, load_json


class StateStore:
    """Represents StateStore."""

    def __init__(self, path: Path = Path("data/state.json")) -> None:
        """Executes __init__ logic."""
        self.path = path
        self._lock = threading.Lock()

    def load(self) -> dict[str, Any]:
        """Executes load logic."""
        if not self.path.exists():
            return {"sites": {}, "updated_at": None}
        return load_json(self.path)

    def save(self, payload: dict[str, Any]) -> None:
        """Executes save logic."""
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        dump_json(self.path, payload)

    def get_site_state(self, site_name: str) -> dict[str, Any]:
        """Executes get_site_state logic."""
        with self._lock:
            payload = self.load()
            return payload.get("sites", {}).get(site_name, {})

    def update_site_state(self, site_name: str, updates: dict[str, Any]) -> None:
        """Executes update_site_state logic."""
        with self._lock:
            payload = self.load()
            site_state = payload.setdefault("sites", {}).setdefault(site_name, {})
            site_state.update(updates)
            self.save(payload)
