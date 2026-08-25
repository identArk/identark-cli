"""Local, privacy-preserving activity records for the first-run experience.

These records are deliberately distinct from the control plane audit log.  They
prove what the developer ran locally without pretending that a local file is a
governed, organisation-wide audit trail.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ACTIVITY_FILE = Path(".identark") / "activity.jsonl"


def record_local_activity(
    project_path: Path,
    *,
    provider: str,
    model: str,
    success: bool,
    cost_usd: float | None = None,
    error_type: str | None = None,
) -> dict[str, Any]:
    """Append a hash-linked, non-sensitive local execution record.

    Prompts, model output, API keys, credential references, and exception
    messages are intentionally excluded.  The record is useful for a first
    local run, but is not represented as immutable server-side audit evidence.
    """
    activity_path = project_path / ACTIVITY_FILE
    activity_path.parent.mkdir(parents=True, exist_ok=True)
    previous_hash = _last_hash(activity_path)
    event: dict[str, Any] = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "kind": "local_llm_run",
        "provider": provider,
        "model": model,
        "success": success,
        "cost_usd": round(cost_usd, 8) if cost_usd is not None else None,
        "error_type": error_type,
        "previous_hash": previous_hash,
    }
    event["hash"] = _event_hash(event)
    with activity_path.open("a", encoding="utf-8") as activity_file:
        activity_file.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
    return event


def read_local_activity(project_path: Path, *, limit: int = 10) -> list[dict[str, Any]]:
    """Read and verify a project's local activity record."""
    activity_path = project_path / ACTIVITY_FILE
    if not activity_path.exists():
        return []

    events: list[dict[str, Any]] = []
    previous_hash: str | None = None
    lines = activity_path.read_text(encoding="utf-8").splitlines()
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ActivityRecordError(f"Invalid activity record on line {line_number}") from exc
        if not isinstance(event, dict):
            raise ActivityRecordError(f"Invalid activity record on line {line_number}")
        event_hash = event.pop("hash", None)
        if not isinstance(event_hash, str) or event.get("previous_hash") != previous_hash:
            raise ActivityRecordError(f"Activity chain verification failed on line {line_number}")
        if _event_hash(event) != event_hash:
            raise ActivityRecordError(f"Activity record hash mismatch on line {line_number}")
        event["hash"] = event_hash
        previous_hash = event_hash
        events.append(event)

    return events[-limit:]


def _last_hash(activity_path: Path) -> str | None:
    if not activity_path.exists():
        return None
    events = read_local_activity(activity_path.parent.parent, limit=1)
    return str(events[-1]["hash"]) if events else None


def _event_hash(event: dict[str, Any]) -> str:
    payload = {key: value for key, value in event.items() if key != "hash"}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ActivityRecordError(Exception):
    """Raised when a local activity record cannot be verified."""
