from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.misc.config_loader import dump_json, load_json


@dataclass(slots=True)
class StateStore:
    path: Path = Path("data/state.json")

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"sites": {}, "updated_at": None}
        return load_json(self.path)

    def save(self, payload: dict[str, Any]) -> None:
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        dump_json(self.path, payload)

    def get_site_state(self, site_name: str) -> dict[str, Any]:
        payload = self.load()
        return payload.setdefault("sites", {}).setdefault(site_name, {})

    def update_site_state(self, site_name: str, updates: dict[str, Any]) -> None:
        payload = self.load()
        site_state = payload.setdefault("sites", {}).setdefault(site_name, {})
        site_state.update(updates)
        self.save(payload)

