"""Regression tests for the secret scanner.

Until 2026-08-17 the value character classes were `[a-zA-Z0-9]`, excluding '-'
and '_'. Since almost every modern key format contains one, the generic rules
matched almost nothing and the scanner reported "No secrets found" on a file
containing a live-looking key. install_git_hook() wires this into a pre-commit
hook, so a false pass is not a silent gap - it is active assurance that the
commit is clean.

IdentArk's own key formats (csk_, ik_live_) had no pattern at all, meaning a
customer could commit their IdentArk credential and be told it was fine.
"""

from __future__ import annotations

import re

import pytest
from identark_cli.core.scanner import SECRET_PATTERNS, _mask_secret, scan_file


def _detects(line: str) -> list[str]:
    return [t for pattern, t, _ in SECRET_PATTERNS if re.search(pattern, line, re.IGNORECASE)]


MUST_DETECT = [
    (
        "openai_project",
        'OPENAI_API_KEY = "' + "sk-" + "proj-abc123def456ghi789jkl012mno345pq" + '"',
    ),
    ("openai_legacy", 'api_key = "sk-' + "a" * 48 + '"'),
    ("anthropic", 'ANTHROPIC_API_KEY = "sk-ant-api03-' + "a" * 40 + '"'),
    ("github_pat", 'token = "ghp_' + "a" * 36 + '"'),
    ("slack_bot", 'SLACK_TOKEN = "' + "xoxb" + "-1234567890123-1234567890123-abcdefghijk" + '"'),
    ("aws_key_id", 'AWS_ACCESS_KEY_ID = "' + "AKIA" + "IOSFODNN7EXAMPLE" + '"'),
    ("identark_csk", 'IDENTARK_API_KEY = "csk_' + "a" * 32 + '"'),
    ("identark_ik_live", 'IDENTARK_API_KEY = "ik_live_' + "a" * 32 + '"'),
    ("google_api_key", 'GOOGLE_KEY = "AIza' + "a" * 35 + '"'),
    ("postgres_url", 'DATABASE_URL = "postgres://user:hunter2@db.host:5432/app"'),
    ("mongo_srv_url", 'MONGO = "mongodb+srv://u:p4ssw0rd@cluster.mongodb.net/db"'),
    ("private_key", "-----BEGIN " + "RSA PRIVATE KEY-----"),
    ("hyphenated_value", 'api_key = "abc-def-ghi-jkl-mno-pqr"'),
]

MUST_NOT_DETECT = [
    ("import_line", "from identark import DirectGateway"),
    ("env_var_deref", 'api_key = os.environ["OPENAI_API_KEY"]'),
    ("short_value", 'token = "abc123"'),
    ("url_without_creds", 'DATABASE_URL = "postgres://localhost:5432/app"'),
    ("plain_prose", "Set your API key in the dashboard before running."),
    ("vault_reference", "identark credential add OPENAI_API_KEY --ref vault://prod/openai"),
]


@pytest.mark.parametrize("name,line", MUST_DETECT, ids=[n for n, _ in MUST_DETECT])
def test_detects_real_key_shapes(name: str, line: str) -> None:
    assert _detects(line), f"{name} went undetected - a false pass blocks nothing"


@pytest.mark.parametrize("name,line", MUST_NOT_DETECT, ids=[n for n, _ in MUST_NOT_DETECT])
def test_does_not_flag_benign_lines(name: str, line: str) -> None:
    assert not _detects(line), f"{name} false-positived as {_detects(line)}"


def test_identark_own_credentials_are_covered() -> None:
    """The scanner must catch the product's own key formats."""
    labels = {t for _, t, _ in SECRET_PATTERNS}
    assert any("IdentArk" in label for label in labels)


def test_hyphen_and_underscore_allowed_in_value_class() -> None:
    """The original bug, pinned directly."""
    pattern = next(p for p, t, _ in SECRET_PATTERNS if t == "API Key")
    assert re.search(pattern, 'api_key = "' + "sk-" + 'abcdefghijklmnop123"', re.IGNORECASE)
    assert re.search(pattern, 'api_key = "' + "ghp_" + 'abcdefghijklmnop123"', re.IGNORECASE)


def test_scan_file_finds_planted_key(tmp_path) -> None:
    """End-to-end: a planted key in a .py file is reported."""
    f = tmp_path / "leaky.py"
    f.write_text('OPENAI_API_KEY = "' + "sk-" + 'proj-abc123def456ghi789jkl012mno345pq"\n')
    findings = list(scan_file(f))
    assert findings, "scan_file missed a planted key"
    assert findings[0].line == 1


def test_scan_file_reads_dotenv(tmp_path) -> None:
    """`.env` has an empty suffix, so extension matching alone skipped it."""
    f = tmp_path / ".env"
    f.write_text("IDENTARK_API_KEY=csk_" + "a" * 32 + "\n")
    assert list(scan_file(f)), ".env was skipped by the extension check"


def test_mask_does_not_leak_the_secret() -> None:
    """The preview is built from the stripped line, so offsets must be re-derived."""
    raw = '    OPENAI_API_KEY = "' + "sk-" + 'proj-abc123def456ghi789jkl012mno345pq"'
    match = re.search(r"\bsk-proj-[A-Za-z0-9_\-]{20,}", raw)
    assert match is not None
    preview = _mask_secret(raw.strip(), match)
    assert "abc123def456" not in preview
    assert "***" in preview
