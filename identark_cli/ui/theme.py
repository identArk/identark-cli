"""Semantic terminal design tokens.

Command modules should use semantic names from this module instead of choosing
ad-hoc Rich colors. That keeps meaning intact when the palette changes.
"""

from __future__ import annotations

from dataclasses import dataclass

BRAND = "bold cyan"
SUCCESS = "green"
ATTENTION = "yellow"
DANGER = "red"
MUTED = "dim"
HEADING = "bold"
COMMAND = "cyan"


@dataclass(frozen=True)
class Symbols:
    """Status symbols with a plain-ASCII fallback."""

    brand: str
    success: str
    attention: str
    failure: str
    inactive: str
    active: str


UNICODE_SYMBOLS = Symbols(
    brand="◈",
    success="✓",
    attention="!",
    failure="×",
    inactive="○",
    active="●",
)

ASCII_SYMBOLS = Symbols(
    brand="*",
    success="OK",
    attention="!",
    failure="X",
    inactive="-",
    active="+",
)
