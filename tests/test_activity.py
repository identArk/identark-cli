"""Regression tests for the honest local first-run activity record."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from identark_cli.core.activity import (
    ActivityRecordError,
    read_local_activity,
    record_local_activity,
)


def test_local_activity_is_hash_linked_and_excludes_sensitive_payloads(tmp_path: Path) -> None:
    record_local_activity(
        tmp_path,
        provider="openai",
        model="gpt-4o-mini",
        success=True,
        cost_usd=0.000123,
    )
    record_local_activity(
        tmp_path,
        provider="openai",
        model="gpt-4o-mini",
        success=False,
        error_type="RateLimitError",
    )

    records = read_local_activity(tmp_path)

    assert len(records) == 2
    assert records[1]["previous_hash"] == records[0]["hash"]
    assert records[0]["cost_usd"] == 0.000123
    assert "prompt" not in records[0]
    assert "output" not in records[0]


def test_local_activity_rejects_tampering(tmp_path: Path) -> None:
    record_local_activity(tmp_path, provider="openai", model="gpt-4o-mini", success=True)
    record_path = tmp_path / ".identark" / "activity.jsonl"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["model"] = "tampered"
    record_path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    with pytest.raises(ActivityRecordError, match="hash mismatch"):
        read_local_activity(tmp_path)
