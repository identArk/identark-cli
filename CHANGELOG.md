# Changelog

All notable changes to `identark-cli` are documented in this file.

This project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

- Public contribution, governance, support, and release documentation.
- Automated checks for public-package boundaries and release artifacts.
- A shared terminal design system with contextual home and status views,
  semantic output components, narrow-terminal support, and `--no-color`.
- Output-safety helpers that redact secret-shaped and terminal-control content
  returned by remote services and MCP tools.
- A runtime-neutral `identark exec` command with agent-bound authentication,
  structured JSON output, idempotent retries, polling, and stable exit codes.

### Changed

- Standardised the repository's GitHub issue forms, pull-request template, and
  supply-chain automation.
- Reworked high-frequency command output around plain-language human approvals,
  governed history, clear recovery steps, and safe generic failure messages.

## [0.1.0] — 2026-09-01

### Added

- Initial alpha release of the IdentArk command-line client.
- Device login, scoped API-key support, credential references, agent
  registration, approval workflows, MCP server registration, and audit-evidence
  verification.

[0.1.0]: https://github.com/identark/identark-cli/releases/tag/v0.1.0
