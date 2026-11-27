# IdentArk Terminal UX

This document defines the public terminal experience for IdentArk CLI. The
interface should feel calm, technical, and helpful: it tells users where they
are, what is safe, and what to do next without exposing internal security
details.

## Product language

Use these terms consistently in user-facing output:

| Say | Meaning |
| --- | --- |
| Human approvals | A person reviews a sensitive operation before it runs |
| Governed history | Authoritative activity recorded through IdentArk |
| Local development | A process may receive the developer's provider secret |
| Gateway Mode | The agent receives a short-lived capability, not a provider secret |

Internal implementation terms such as “HITL” and “control plane” belong in
architecture documentation, not primary command labels or recovery messages.

## Information hierarchy

Running `identark` without arguments is a contextual home screen, not a wall of
help. It presents, in order:

1. Product identity and version.
2. Account, current project, and operating mode.
3. At most three state-aware next steps with exact commands.
4. One short security-boundary reminder.

Full command discovery remains available through `identark --help`. Commands
are grouped by user intent: Get started, Build, Account, and Govern.

## Components and semantic color

All human-readable output should use the shared helpers in `identark_cli/ui/`.
Command modules should not create their own console or choose ad hoc colors.

| Token | Use |
| --- | --- |
| Brand / command | IdentArk identity and executable commands |
| Success | A requested operation completed |
| Attention | A recoverable state or required review |
| Danger | A failure that prevented the requested outcome |
| Muted | Supporting context and security notes |

Color never carries meaning alone. Every state also has a label or symbol. The
CLI honors `NO_COLOR`, `TERM=dumb`, and the global `--no-color` option. Unicode
status symbols fall back to ASCII when the terminal encoding cannot support
them. Core views must remain understandable at 40, 80, and 120 columns.

## Errors and empty states

An error states the outcome first, adds a brief explanation when useful, and
offers one concrete recovery command when one exists. Unknown exception text is
never printed because upstream errors can contain credentials or remote data.

An empty state explains what is absent, why that is normal, and the command that
creates or watches the resource. Empty states are guidance, not failures.

## Output safety

Treat server fields, MCP tool results, and other remote values as untrusted.
Before rendering them:

- recursively redact sensitive keys and known credential shapes;
- remove ANSI and terminal control characters;
- escape Rich markup;
- bound long values before placing them in panels or tables;
- never echo credential values, provider keys, capability tokens, or arbitrary
  response bodies;
- never print the complete child-process argument vector after credential
  injection.

Use `redact_sensitive` for structured values and `safe_rich_text` for a value
placed inside Rich markup. Security failures must remain fail-closed: the UX
layer may clarify a denial, but it cannot weaken policy or approval behavior.

## Automation contract

The current output is designed for people. Automation may rely on documented
commands and exit codes, but must not scrape styled text. A future JSON or quiet
mode needs its own versioned schema, tests, and compatibility policy before it
is advertised as stable.

## Next extension: approval attention signals

The next CLI extension should notify an operator when a new human approval is
waiting. Build it on the existing `identark approvals watch` flow before adding
a background daemon or native notification service.

The first implementation should:

- ring the terminal bell once when a previously unseen approval ID appears;
- enable the signal for an interactive paused agent and while a user explicitly
  runs `identark approvals watch`;
- provide `--no-bell` and a persistent preference for users and assistive
  environments that do not want an audible or visual signal;
- deduplicate notifications across polling and reconnects;
- show only safe metadata such as risk band, tool label, and expiry;
- route every displayed remote value through the output-safety layer;
- require a separate `inspect`, `approve`, or `reject` command;
- preserve MFA or reauthentication for high-risk decisions;
- treat timeout, connection loss, and malformed events as denial, never
  approval.

The notification is an attention signal, not an authorization mechanism. It
must never include tool arguments, prompts, customer data, credential values,
capability tokens, or arbitrary response text. It must not steal terminal
focus, repeat continuously, or create any client-side auto-approval path.

Native operating-system notifications and a continuously running background
process remain out of scope until user demand justifies their lifecycle and
security complexity. Automatic approval signals are authoritative only for
operations routed through Gateway Mode.
