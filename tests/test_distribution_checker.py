"""Adversarial tests for the release-archive boundary checker."""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

CLI_ROOT = Path(__file__).parents[1]
CHECKER = CLI_ROOT / "scripts" / "check_distribution.py"


def _write_wheel(path: Path, files: dict[str, str]) -> None:
    with zipfile.ZipFile(path, mode="w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)


def _check(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECKER), str(path)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_distribution_checker_accepts_public_cli_wheel(tmp_path: Path) -> None:
    wheel = tmp_path / "identark_cli-1.0.0-py3-none-any.whl"
    _write_wheel(
        wheel,
        {
            "identark_cli/__init__.py": '__version__ = "1.0.0"\n',
            "identark_cli-1.0.0.dist-info/METADATA": "Name: identark-cli\n",
        },
    )

    result = _check(wheel)

    assert result.returncode == 0, result.stderr


def test_distribution_checker_rejects_private_control_plane_file(tmp_path: Path) -> None:
    wheel = tmp_path / "identark_cli-1.0.0-py3-none-any.whl"
    _write_wheel(
        wheel,
        {
            "identark_cli/__init__.py": "",
            "app/settings.py": "SECRET_KEY = 'not-for-publication'\n",
        },
    )

    result = _check(wheel)

    assert result.returncode == 1
    assert "forbidden path component" in result.stderr


def test_distribution_checker_rejects_private_control_plane_import(tmp_path: Path) -> None:
    wheel = tmp_path / "identark_cli-1.0.0-py3-none-any.whl"
    _write_wheel(
        wheel,
        {
            "identark_cli/__init__.py": "from app.dependencies import get_current_user\n",
        },
    )

    result = _check(wheel)

    assert result.returncode == 1
    assert "private control-plane import" in result.stderr


def test_distribution_checker_rejects_private_key_material(tmp_path: Path) -> None:
    wheel = tmp_path / "identark_cli-1.0.0-py3-none-any.whl"
    header = "-----BEGIN " + "PRIVATE KEY-----"
    _write_wheel(wheel, {"identark_cli/fixture.txt": header})

    result = _check(wheel)

    assert result.returncode == 1
    assert "private key material" in result.stderr
