"""Reusable, accessible terminal components for human-readable output."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from identark_cli.ui.copy import TAGLINE
from identark_cli.ui.theme import (
    ASCII_SYMBOLS,
    ATTENTION,
    BRAND,
    COMMAND,
    DANGER,
    HEADING,
    MUTED,
    SUCCESS,
    UNICODE_SYMBOLS,
    Symbols,
)


@dataclass(frozen=True)
class StatusRow:
    """One non-sensitive item in a terminal context summary."""

    label: str
    value: str
    state: str = "neutral"


@dataclass(frozen=True)
class NextStep:
    """A recommended user action and the exact command that performs it."""

    label: str
    command: str


def symbols_for(console: Console) -> Symbols:
    """Return glyphs supported by the console encoding."""
    encoding = (console.encoding or "").lower()
    return UNICODE_SYMBOLS if "utf" in encoding else ASCII_SYMBOLS


def render_header(console: Console, *, version: str) -> None:
    """Render the compact IdentArk product identity."""
    symbols = symbols_for(console)
    console.print()
    console.print(
        Text.assemble(
            (f"  {symbols.brand} ", BRAND),
            ("IdentArk", "bold"),
            (f"  v{version}", MUTED),
        )
    )
    console.print(Text(f"  {TAGLINE}", style=MUTED))


def render_context_summary(console: Console, rows: Sequence[StatusRow]) -> None:
    """Render account, project, and operating-mode context without a heavy box."""
    table = Table.grid(padding=(0, 3))
    table.add_column(style=MUTED, no_wrap=True)
    table.add_column()
    styles = {
        "active": SUCCESS,
        "attention": ATTENTION,
        "danger": DANGER,
        "neutral": "",
    }
    for row in rows:
        table.add_row(row.label, Text(row.value, style=styles.get(row.state, "")))
    console.print()
    console.print(table)


def render_next_steps(
    console: Console, steps: Sequence[NextStep], *, title: str = "Next steps"
) -> None:
    """Render a short, ordered action path."""
    if not steps:
        return
    console.print()
    console.print(Text(title, style=HEADING))
    for position, step in enumerate(steps, start=1):
        console.print(Text.assemble((f"{position}. ", MUTED), step.label))
        console.print(Text(f"   {step.command}", style=COMMAND))


def render_security_note(console: Console, message: str) -> None:
    """Render a calm security boundary reminder."""
    console.print()
    console.print(Text(f"  {message}", style=MUTED))


def render_success(console: Console, message: str) -> None:
    """Render a successful outcome."""
    console.print(Text.assemble((f"{symbols_for(console).success} ", SUCCESS), message))


def render_warning(console: Console, message: str, *, next_step: str | None = None) -> None:
    """Render a recoverable warning and optional remedy."""
    body: list[RenderableType] = [
        Text.assemble((f"{symbols_for(console).attention} ", ATTENTION), message)
    ]
    if next_step:
        body.append(Text.assemble(("  Next: ", MUTED), (next_step, COMMAND)))
    console.print(Group(*body))


def render_error(
    console: Console,
    message: str,
    *,
    explanation: str | None = None,
    next_step: str | None = None,
) -> None:
    """Render a safe error without interpolating an unknown exception."""
    body: list[RenderableType] = [
        Text.assemble((f"{symbols_for(console).failure} ", DANGER), message)
    ]
    if explanation:
        body.append(Text(f"  {explanation}", style=MUTED))
    if next_step:
        body.append(Text.assemble(("  Next: ", MUTED), (next_step, COMMAND)))
    console.print(Group(*body))


def render_empty_state(
    console: Console,
    title: str,
    explanation: str,
    *,
    next_step: str | None = None,
) -> None:
    """Render an empty state with context and a way forward."""
    body: list[RenderableType] = [Text(title, style=HEADING), Text(explanation, style=MUTED)]
    if next_step:
        body.append(Text.assemble(("Next: ", MUTED), (next_step, COMMAND)))
    console.print(Panel.fit(Group(*body), border_style="dim", padding=(0, 1)))
