# Contributing to IdentArk CLI

Thank you for helping make secure agent infrastructure easier to use.

Please read the [Code of Conduct](CODE_OF_CONDUCT.md) and
[governance model](GOVERNANCE.md) before contributing.

The CLI is open source, but the hosted IdentArk control plane is not. This
repository communicates with the service only through documented public HTTPS
contracts. Do not add imports from, or rely on, private service implementation
details.

## Development setup

Requirements:

- Python 3.11 or newer
- `uv` 0.12.5 or newer

From this repository checkout:

```bash
uv sync --locked --extra dev
uv run pytest
uv run ruff format --check identark_cli tests scripts
uv run ruff check identark_cli tests scripts
uv run mypy identark_cli
```

To verify the package boundary:

```bash
uv build
uv run python scripts/check_distribution.py dist/*
```

## Contribution rules

- Communicate with IdentArk only through documented public API contracts.
- Never import `app`, `cloud`, migrations, infrastructure, or deployment code.
- Never include real credentials, tokens, customer data, private endpoints, or
  production configuration in source, fixtures, recordings, or documentation.
- Use synthetic secret-shaped strings only when a scanner test requires them,
  and construct them in the test so automated secret scanners do not mistake
  them for live credentials.
- Do not print tokens or credential values. Redact sensitive error details.
- Keep authentication state in the OS keychain when possible. Any fallback
  storage must retain restrictive permissions and an explicit warning.
- Treat all CLI inputs as untrusted. The server remains authoritative for
  authentication, authorization, risk, approval, and audit policy.
- Add tests for behavior and security boundaries changed by the pull request.

## Before you start

Small documentation corrections and focused bug fixes can go directly to a pull
request. For new commands, integrations, dependencies, public API changes, or
changes to authentication, credential handling, audit evidence, or approval
behaviour, open an issue and agree on the design first.

Useful contribution areas include documentation, tests, usability improvements,
accessibility, command output, and reproducible bug reports. Please keep a pull
request focused; unrelated refactors make security review harder.

## Pull requests

Keep changes focused and describe:

1. the user problem;
2. the security impact and trust boundaries;
3. tests performed;
4. any public API or compatibility impact;
5. documentation that changed.

Changes that weaken credential isolation, token handling, audit behavior, or
the package boundary will not be accepted.

## Commit sign-off

Contributions use the [Developer Certificate of Origin
1.1](https://developercertificate.org/). Sign each commit with:

```bash
git commit -s -m "fix: concise description"
```

The sign-off certifies that you have the right to submit the work under the MIT
license. Conventional Commit prefixes such as `feat`, `fix`, `docs`, `test`,
`refactor`, and `chore` are encouraged.

## License

By contributing, you agree that your contributions are licensed under the
repository's [MIT License](LICENSE).

## Security reports

Do not open a public issue for a suspected vulnerability. Follow
[`SECURITY.md`](SECURITY.md) instead.
