"""Output-safety helpers for untrusted server and tool values."""

from __future__ import annotations

import re
from typing import Any

from rich.markup import escape

from identark_cli.core.scanner import SECRET_PATTERNS

REDACTED = "*** REDACTED ***"
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f-\x9f]")
SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)


def redact_sensitive(value: Any) -> Any:
    """Return a display-safe copy of nested untrusted data."""
    if isinstance(value, dict):
        return {
            key: (
                REDACTED
                if any(part in str(key).lower() for part in SENSITIVE_KEY_PARTS)
                else redact_sensitive(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive(item) for item in value)
    if isinstance(value, str):
        return redact_secret_text(value)
    return value


def redact_secret_text(value: str) -> str:
    """Replace known credential shapes in an untrusted string."""
    text = value
    for pattern, _secret_type, _confidence in SECRET_PATTERNS:
        text = re.sub(pattern, REDACTED, text, flags=re.IGNORECASE)
    return re.sub(
        r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+\-/]+=*",
        REDACTED,
        text,
    )


def safe_rich_text(value: Any, *, max_length: int = 1000) -> str:
    """Redact, bound, and escape an untrusted value for Rich markup."""
    # Strip terminal controls before pattern matching so an ANSI sequence
    # cannot be inserted into a credential prefix to evade redaction.
    text = ANSI_ESCAPE.sub("", str(value))
    # ANSI_ESCAPE only deletes full CSI sequences; a bare \x1b, a newline or any
    # other C0/C1 character survives it. Substituting a space for those would
    # split `csk_\x1bAKIA...` into `csk_ AKIA...`, which no SECRET_PATTERNS rule
    # matches - the credential would then print unredacted. So detection runs on
    # the form where control characters are *deleted*, and that form is what gets
    # displayed whenever it exposes a credential the spaced form would have hidden.
    spliced = CONTROL_CHARACTERS.sub("", text)
    redacted_spliced = redact_secret_text(spliced)
    if redacted_spliced != spliced:
        text = redacted_spliced
    else:
        # Nothing hides behind the control characters, so keep them as spaces to
        # stay readable, and still redact (a space can complete an assignment shape).
        text = redact_secret_text(CONTROL_CHARACTERS.sub(" ", text))
    if len(text) > max_length:
        text = text[: max_length - 1] + "…"
    return escape(text)
