"""
Secret scanner for IdentArk CLI

Detects potential secrets, API keys, and credentials in source code.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SecretFinding:
    """A potential secret finding"""

    file: Path
    line: int
    secret_type: str
    preview: str
    confidence: str  # high, medium, low


# Patterns for secret detection
#
# NOTE ON CHARACTER CLASSES
# Value classes must include '-' and '_'. Until 2026-08-17 they did not, so
# `api_key = "sk-..."` and `api_key = "ghp_..."` both slipped through: the class
# stopped dead at the first hyphen. Almost every modern key format carries one,
# which left the generic rules close to inert while the scanner still reported
# "no secrets found" - a false pass, which is worse than no scanner at all
# because install_git_hook() turns it into active assurance at commit time.
#
# Vendor-prefixed keys match on their prefix and do not depend on the assignment
# shape, so they are caught in .env, YAML, JSON and prose alike.
SECRET_PATTERNS = [
    # --- IdentArk's own credentials (previously not covered at all) ---
    (r"\bcsk_[A-Za-z0-9_\-]{16,}", "IdentArk Control-Plane Key", "high"),
    (r"\bik_(live|test)_[A-Za-z0-9_\-]{16,}", "IdentArk API Key", "high"),
    # --- OpenAI ---
    (r"\bsk-proj-[A-Za-z0-9_\-]{20,}", "OpenAI Project Key", "high"),
    (r"\bsk-[A-Za-z0-9]{20,}T3BlbkFJ[A-Za-z0-9]{20,}", "OpenAI API Key", "high"),
    (r"\bsk-[A-Za-z0-9]{48}\b", "OpenAI API Key (legacy)", "high"),
    # --- Anthropic (real keys look like sk-ant-api03-..., so allow - and _) ---
    (r"\bsk-ant-[A-Za-z0-9_\-]{24,}", "Anthropic API Key", "high"),
    # --- Cloud / VCS / chat ---
    (r"\bAKIA[0-9A-Z]{16}\b", "AWS Access Key ID", "high"),
    (
        r"aws[_-]?secret[_-]?access[_-]?key['\"]?\s*[:=]\s*['\"][A-Za-z0-9/+=]{40}['\"]",
        "AWS Secret Key",
        "high",
    ),
    (r"\bgh[pousr]_[A-Za-z0-9]{36,}", "GitHub Token", "high"),
    (r"\bxox[baprs]-[0-9]{10,13}-[0-9]{10,13}[A-Za-z0-9-]*", "Slack Token", "high"),
    (r"\bAIza[0-9A-Za-z_\-]{35}\b", "Google API Key", "high"),
    # --- Generic assignment shapes ---
    (r"api[_-]?key['\"]?\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]", "API Key", "high"),
    (r"api[_-]?secret['\"]?\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]", "API Secret", "high"),
    (r"password['\"]?\s*[:=]\s*['\"][^'\"\s]{8,}['\"]", "Hardcoded Password", "medium"),
    (r"secret['\"]?\s*[:=]\s*['\"][^'\"\s]{8,}['\"]", "Hardcoded Secret", "medium"),
    (r"token['\"]?\s*[:=]\s*['\"][A-Za-z0-9_\-]{20,}['\"]", "Token", "medium"),
    # --- Key material and connection strings ---
    (r"-----BEGIN (RSA |DSA |EC |OPENSSH |PGP )?PRIVATE KEY-----", "Private Key", "high"),
    (
        r"(postgres|postgresql|mysql|mongodb)(\+srv)?://[^:@/\s]+:[^@/\s]+@",
        "Database URL with Password",
        "high",
    ),
]

# File patterns to scan
SCAN_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".rb",
    ".go",
    ".rs",
    ".java",
    ".php",
    ".sh",
    ".yml",
    ".yaml",
    ".json",
    ".toml",
    ".env",
}

# Files/directories to ignore
IGNORE_PATTERNS = [
    r"\.git/",
    r"node_modules/",
    r"__pycache__/",
    r"\.venv/",
    r"venv/",
    r"\.identark/",
    r"\.env\.example",
    r"dist/",
    r"build/",
    r"\.egg-info/",
    r"vendor/",
]


def scan_directory(path: Path, max_file_size: int = 1024 * 1024) -> list[SecretFinding]:
    """
    Scan directory for secrets

    Args:
        path: Directory to scan
        max_file_size: Maximum file size to scan (1MB default)

    Returns:
        List of secret findings
    """
    findings = []

    for file_path in _iter_files(path):
        # Check file size
        try:
            if file_path.stat().st_size > max_file_size:
                continue
        except OSError:
            continue

        # Scan file
        for finding in scan_file(file_path):
            findings.append(finding)

    return findings


def scan_file(file_path: Path) -> Iterator[SecretFinding]:
    """Scan a single file for secrets"""
    # Skip binary files
    if file_path.suffix not in SCAN_EXTENSIONS and file_path.name not in SCAN_EXTENSIONS:
        return

    try:
        with open(file_path, encoding="utf-8", errors="ignore") as f:
            content = f.read()
            lines = content.split("\n")
    except OSError:
        return

    for line_num, line in enumerate(lines, start=1):
        for pattern, secret_type, confidence in SECRET_PATTERNS:
            matches = re.finditer(pattern, line, re.IGNORECASE)
            for match in matches:
                # Skip false positives in comments for low confidence
                if confidence == "low" and _is_likely_false_positive(line):
                    continue

                # Create preview (mask the actual secret)
                preview = _mask_secret(line.strip(), match)

                yield SecretFinding(
                    file=file_path,
                    line=line_num,
                    secret_type=secret_type,
                    preview=preview,
                    confidence=confidence,
                )


def _iter_files(path: Path) -> Iterator[Path]:
    """Iterate over files to scan"""
    if path.is_file():
        if not _should_ignore(path):
            yield path
        return

    for item in path.rglob("*"):
        if item.is_file() and not _should_ignore(item):
            yield item


def _should_ignore(file_path: Path) -> bool:
    """Check if file should be ignored"""
    path_str = str(file_path)

    for pattern in IGNORE_PATTERNS:
        if re.search(pattern, path_str):
            return True

    return False


def _is_likely_false_positive(line: str) -> bool:
    """Check if line is likely a false positive"""
    # Skip comments explaining what to do
    if re.search(r"#.*(set|put|replace|your|example|placeholder)", line, re.IGNORECASE):
        return True

    # Skip documentation
    if line.strip().startswith(("#", "//", "/*", "*", '"""', "'''")):
        return True

    return False


def _mask_secret(line: str, match: re.Match[str]) -> str:
    """Mask the secret portion of a line for display"""
    secret = match.group(0)
    start = line.find(secret)
    if start == -1:
        return line
    end = start + len(secret)

    # Mask most of the secret
    if len(secret) > 8:
        masked = secret[:4] + "***" + secret[-4:]
    else:
        masked = "****"

    return line[:start] + masked + line[end:]


def install_git_hook(project_path: Path) -> None:
    """
    Install pre-commit hook to scan for secrets

    Args:
        project_path: Project root directory
    """
    hook_path = project_path / ".git" / "hooks" / "pre-commit"

    if not hook_path.parent.exists():
        raise HookInstallError(f"Not a git repository: {project_path}")

    if hook_path.exists():
        existing = hook_path.read_text(encoding="utf-8", errors="ignore")
        if "IdentArk secret scanner pre-commit hook" in existing:
            return
        raise HookInstallError(
            "A pre-commit hook already exists. Add `identark credential scan --strict` "
            "to that hook manually so IdentArk does not overwrite it."
        )

    hook_content = """#!/bin/sh
# IdentArk secret scanner pre-commit hook

if ! command -v identark >/dev/null 2>&1; then
    echo "Commit blocked: IdentArk CLI is required by the installed secret-scan hook"
    exit 1
fi

echo "Scanning for secrets..."
if ! identark credential scan --strict; then
    echo "Commit blocked: secrets detected or the scanner failed"
    exit 1
fi

exit 0
"""

    hook_path.write_text(hook_content, encoding="utf-8")
    hook_path.chmod(0o755)


def remove_git_hook(project_path: Path) -> None:
    """Remove pre-commit hook"""
    hook_path = project_path / ".git" / "hooks" / "pre-commit"

    if hook_path.exists():
        # Only remove if it's our hook
        content = hook_path.read_text(encoding="utf-8")
        if "IdentArk" in content:
            hook_path.unlink()


class HookInstallError(Exception):
    """Raised when a git hook cannot be installed without overwriting user configuration."""
