# Contributing to IdentArk CLI

Thank you for helping make secure agent infrastructure easier to use.

The CLI is open source, but the hosted IdentArk control plane is not. Until the
CLI is extracted to its dedicated repository, contributions must stay entirely
within `cli/`. Do not add imports from the parent repository or rely on private
control-plane implementation details.

## Development setup

Requirements:

- Python 3.11 or newer
- `uv` 0.12.5 or newer

From the control-plane repository checkout:

```bash
uv sync --project cli --locked --extra dev
uv run --project cli pytest cli/tests
uv run --project cli ruff format --check --config cli/pyproject.toml cli/identark_cli cli/tests cli/scripts
uv run --project cli ruff check --config cli/pyproject.toml cli/identark_cli cli/tests cli/scripts
uv run --project cli mypy --config-file cli/pyproject.toml cli/identark_cli
```

To verify the package boundary:

```bash
uv build cli
uv run --project cli python cli/scripts/check_distribution.py cli/dist/*
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

## Pull requests

Keep changes focused and describe:

1. the user problem;
2. the security impact and trust boundaries;
3. tests performed;
4. any public API or compatibility impact;
5. documentation that changed.

Changes that weaken credential isolation, token handling, audit behavior, or
the package boundary will not be accepted.

## Security reports

Do not open a public issue for a suspected vulnerability. Follow
[`SECURITY.md`](SECURITY.md) instead.
