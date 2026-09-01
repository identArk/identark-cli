from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from identark_cli import __version__

CLI_ROOT = Path(__file__).parents[1]
SCRIPT = CLI_ROOT / "scripts" / "check_release_version.py"


def test_release_version_check_accepts_matching_tag() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), f"v{__version__}"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert f"matches identark-cli {__version__}" in completed.stdout


def test_release_version_check_rejects_mismatched_tag() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "v999.999.999"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert "does not match package version" in completed.stderr
