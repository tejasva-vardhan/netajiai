"""Generate reviewable v1 API and event contract artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from backend.app.api.main import app
from backend.app.contracts.events import ComplaintLifecycleEvent


ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    _write_json(ROOT / "docs/contracts/openapi-v1.json", app.openapi())
    _write_json(
        ROOT / "docs/contracts/events/complaint-lifecycle-v1.schema.json",
        ComplaintLifecycleEvent.model_json_schema(),
    )


if __name__ == "__main__":
    main()
