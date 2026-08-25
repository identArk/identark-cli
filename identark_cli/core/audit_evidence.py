"""Offline verification for portable, non-secret approval-chain evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

EVIDENCE_FORMAT = "identark.approval-chain.evidence/v1"
EVIDENCE_CANONICALIZATION = "python-json-sort-keys-v1"
_PAYLOAD_FIELDS = frozenset(
    {
        "approval_id",
        "request_id",
        "decision",
        "approver_id",
        "mfa_verified",
        "risk_score",
        "tool_name",
        "requested_at",
        "decided_at",
        "previous_hash",
    }
)


class AuditEvidenceError(ValueError):
    """Raised when an evidence bundle is structurally unsafe to verify."""


@dataclass(frozen=True)
class EvidenceVerification:
    """The result of independently walking one supplied evidence bundle."""

    valid: bool
    records_checked: int
    head_hash: str | None
    failure_position: int | None = None
    failure_reason: str | None = None


def compute_hash(payload: dict[str, Any]) -> str:
    """Reproduce the v1 approval-chain digest without importing server code."""
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def verify_evidence_bundle(bundle: object) -> EvidenceVerification:
    """Verify the hashes and ordering in a portable evidence bundle offline.

    The result intentionally makes a narrow claim: integrity of the supplied
    records. An offline file cannot establish that a server exported every
    record, nor can it attest where that file originated.
    """
    if not isinstance(bundle, dict):
        raise AuditEvidenceError("evidence must be a JSON object")
    if bundle.get("format") != EVIDENCE_FORMAT:
        raise AuditEvidenceError("unsupported evidence format")
    if bundle.get("algorithm") != "sha256":
        raise AuditEvidenceError("unsupported evidence hash algorithm")
    if bundle.get("canonicalization") != EVIDENCE_CANONICALIZATION:
        raise AuditEvidenceError("unsupported evidence canonicalization")

    records = bundle.get("records")
    if not isinstance(records, list):
        raise AuditEvidenceError("evidence records must be a list")

    expected_previous: str | None = None
    for position, record in enumerate(records):
        if not isinstance(record, dict):
            raise AuditEvidenceError("evidence record must be an object")
        approval_id = record.get("approval_id")
        payload = record.get("hashed_payload")
        stored_hash = record.get("record_hash")
        previous_hash = record.get("previous_hash")
        if not isinstance(approval_id, str) or not approval_id:
            raise AuditEvidenceError("evidence record is missing its approval identifier")
        if not isinstance(payload, dict) or set(payload) != _PAYLOAD_FIELDS:
            raise AuditEvidenceError("evidence record has an unexpected hashed payload")
        if payload.get("approval_id") != approval_id:
            raise AuditEvidenceError("evidence record identifier does not match its hashed payload")
        if payload.get("previous_hash") != previous_hash:
            raise AuditEvidenceError(
                "evidence record predecessor does not match its hashed payload"
            )
        if not isinstance(stored_hash, str) or not stored_hash:
            raise AuditEvidenceError("evidence record is missing its stored hash")
        if previous_hash is not None and not isinstance(previous_hash, str):
            raise AuditEvidenceError("evidence record predecessor must be a string or null")

        computed_hash = compute_hash(payload)
        if stored_hash != computed_hash:
            return EvidenceVerification(
                valid=False,
                records_checked=position + 1,
                head_hash=expected_previous,
                failure_position=position,
                failure_reason="record hash does not match its hashed payload",
            )
        if previous_hash != expected_previous:
            return EvidenceVerification(
                valid=False,
                records_checked=position + 1,
                head_hash=expected_previous,
                failure_position=position,
                failure_reason="record predecessor does not match the preceding record",
            )
        expected_previous = stored_hash

    if bundle.get("chain_head") != expected_previous:
        return EvidenceVerification(
            valid=False,
            records_checked=len(records),
            head_hash=expected_previous,
            failure_position=None,
            failure_reason="declared chain head does not match the supplied records",
        )
    return EvidenceVerification(
        valid=True,
        records_checked=len(records),
        head_hash=expected_previous,
    )
