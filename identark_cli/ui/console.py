"""Process-wide Rich consoles and terminal capability configuration."""

from __future__ import annotations

import os

from rich.console import Console

# Highlighting arbitrary values can make identifiers look like syntax and can
# accidentally draw attention to sensitive-looking substrings. Styles are
# therefore always explicit in IdentArk output.
console = Console(highlight=False)
error_console = Console(stderr=True, highlight=False)


def configure_console(*, no_color: bool = False) -> None:
    """Apply global output preferences before rendering a command."""
    disable_color = no_color or "NO_COLOR" in os.environ or os.environ.get("TERM") == "dumb"
    console.no_color = disable_color
    error_console.no_color = disable_color
