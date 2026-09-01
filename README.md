# IdentArk CLI

The command-line client for IdentArk credential references, agent registration,
human approval workflows, and local development injection.

> Release status: alpha. The package is prepared for `identark-cli` on PyPI but
> has not been published yet. Install it from this repository until the first
> trusted-publishing release completes.

## Requirements

- Python 3.11 or newer
- An IdentArk account or scoped `csk_` API key
- An OS keychain for device-login tokens, when available

## Install from source

```bash
git clone https://github.com/identark/identark-cli.git
cd identark-cli
python -m pip install -e .
identark --version
```

After the first release:

```bash
python -m pip install identark-cli
```

## Authenticate

Interactive device login opens the IdentArk authorization page and stores the
resulting Firebase session in the OS keychain:

```bash
identark auth login
identark auth status
```

For headless environments, print the URL instead of opening a browser:

```bash
identark auth login --no-browser
```

For CI and agent automation, prefer a narrowly scoped key that is supplied by
the runtime and is never persisted by the CLI:

```bash
export IDENTARK_API_KEY='csk_...'
identark auth token
```

`identark auth token` reports the token source and storage backend but never
prints the raw token. If an OS keychain is unavailable, the CLI warns and uses
`~/.identark/credentials.toml` with mode `0600`; any process running as that OS
user can still read that fallback file.

## Project setup

### First run: prove the path locally

Choose a provider and generate a runnable sample in one command. The command
stores only an `env://` reference in `.identark/config.toml`; it never asks for,
prints, or writes a provider key.

```bash
# Choose one: openai, anthropic, or ollama
identark init --provider openai
pip install "identark[openai]"
export OPENAI_API_KEY='…' # set in your shell, never in the project
identark agent run identark_sample.py
identark trail
```

The generated sample makes one real provider call through `DirectGateway` and
writes a hash-linked, privacy-preserving local activity record at
`.identark/activity.jsonl`. It records only provider, model, time, success, and
estimated cost—never prompts, model output, credential values, references, or
exception text. The file is ignored by Git.

This is intentionally **not** the control-plane audit trail: local development
places the provider key in the sample process for that process lifetime. When
you move to Gateway Mode, the agent receives a scoped IdentArk token instead of
the provider credential. Inspect the resulting authoritative audit records with:

```bash
identark audit list
```

### Promote a working sample to Gateway Mode

Connect a normal API-key provider from the terminal, with no dashboard hunting
and no secret placed in shell history or a project file:

```bash
identark credential connect openai
# Paste the key twice into the hidden prompt.
```

The key goes directly over the authenticated HTTPS connection to the IdentArk
vault. The CLI never accepts it as a command-line argument, never prints it,
and never writes it to `.identark/config.toml`. It returns only a vault
reference. For providers that require multiple fields, use the documented
structured-credential setup instead.

Then promote the project with that **reference**—never the credential value:

```bash
identark promote --credential-ref secret/orgs/<org-id>/providers/openai --provider openai
python identark_gateway_sample.py
identark audit list
```

`promote` registers (or reuses) the agent, creates a bounded session, and mints
a 15-minute `llm:invoke` capability bound to that agent. The capability is put
directly in the OS keychain (or its mode-`0600` fallback), while
`.identark/config.toml` contains only non-secret metadata. The generated
`identark_gateway_sample.py` is separate from the local sample and uses
`ControlPlaneGateway`; it never reads a provider credential.

Run a governed smoke test as part of promotion only when you intend to make a
provider call, since it may incur a charge:

```bash
identark promote --credential-ref secret/orgs/<org-id>/providers/openai --provider openai --run
```

The capability can invoke only the registered agent's session. It cannot read
or administer credentials, and it expires automatically. Re-run `promote` to
mint a fresh short-lived capability when needed.

### Export approval evidence for an independent reviewer

After a governed workflow has produced HITL decisions, a human with an
IdentArk login can export the decision chain and give the resulting file to an
auditor or customer. The reviewer does not need IdentArk access to verify it:

```bash
identark audit export --output identark-approval-evidence.json
identark audit verify identark-approval-evidence.json
```

The bundle contains only decision fields covered by the hash chain—such as the
tool name, risk score, decision, timestamps, and preceding hash. It never
contains tool arguments, prompts, model output, credential values, or
capability tokens. `audit verify` recomputes every SHA-256 digest and chain
link locally, without an API call.

This is deliberately a narrow claim: it proves the integrity and order of the
records supplied in the bundle. It cannot prove that an exporter included every
historical record or independently attest the bundle's origin; those require a
separately anchored or signed checkpoint.

### Export risk and policy decision evidence (v2)

New approvals can also carry a separate, backwards-compatible v2 evidence
chain. It explains the numeric risk factors, categorical indicators, and the
policy decision that required review, while linking each explanation to the
corresponding v1 approval hash:

```bash
identark audit export --format v2 --output identark-decision-evidence.json
identark audit verify identark-decision-evidence.json
```

V2 never changes or replaces v1. Verify the linked v1 bundle separately when
you need to check both the approval decision and its explanation. To keep the
portable file safe, it excludes tool arguments, prompts, outputs, credentials,
capability tokens, policy expressions, and policy condition values. Matched
policy metadata includes a version digest that an authorised reviewer can
compare with the policy they hold.

### Manual project setup

```bash
identark init
identark credential add ANTHROPIC_API_KEY --ref vault://prod/anthropic
identark credential list
identark credential scan --strict
```

Credential names must be valid environment-variable names. References are
limited to `vault://...` and `env://...`; secret values are never written to
`.identark/config.toml`.

The pre-commit scanner is opt-in and refuses to overwrite an existing hook:

```bash
identark credential install-hook
```

Once installed, the hook fails closed if the `identark` executable is missing
or the scan fails.

## Local agent development

Create a scaffold and run its generated `src/main.py`:

```bash
identark agent init --name my-agent --template basic
cd my-agent
identark credential add API_KEY --ref vault://prod/provider
identark agent run
```

Available templates are `basic`, `slack-bot`, and `api-service`.

Register the agent with the real control-plane endpoint separately:

```bash
identark agent register \
  --name my-agent \
  --provider anthropic \
  --model claude-sonnet-4-5 \
  --credential-ref vault://prod/anthropic

identark agent list
```

### Important isolation boundary

`identark agent run`, `identark agent dev`, and `identark credential inject`
resolve scalar credentials and place them in the child process environment.
The child process can read those values. This is useful for local development,
but it is not a “secret never reaches the agent” boundary.

For production database access or other operations where the agent must never
receive a raw credential, use an IdentArk managed connector/executor. Structured
credentials such as Neon database credentials are deliberately refused by local
environment injection.

The `trail` command verifies the hash-linked local development record. It is
useful for confirming a first run without exposing sensitive content, but it is
not compliance evidence. `audit list` reads the append-only control-plane audit
log and shows only activity that actually passed through a governed route.

## Human approvals

```bash
identark approvals list
identark approvals inspect <approval-id>
identark approvals approve <approval-id>
identark approvals reject <approval-id> --reason "Not expected"
identark approvals watch
```

`watch` is a read-only monitor. Approvals always require an explicit command;
there is no client-side auto-approve mode. Sensitive-looking keys in displayed
tool arguments are recursively redacted. Server policy remains authoritative,
and approval timeout defaults to deny.

## MCP servers

```bash
identark mcp server list
identark mcp server add \
  --name public-tools \
  --endpoint https://mcp.example.com/rpc \
  --transport streamable_http
identark mcp server show <server-id>
identark mcp tool list --server <server-id>
identark mcp tool execute \
  --server <server-id> \
  --tool search \
  --args '{"query":"example"}'
```

CLI registration accepts only absolute HTTPS endpoints using `http_sse` or
`streamable_http`. Version 0.1 does not collect raw MCP bearer tokens or API
keys. Authenticated MCP registration will be exposed only after the API accepts
vault references rather than secret values. Capability discovery is also not
advertised until the backend performs real discovery.

## Configuration

Project configuration lives in `.identark/config.toml`. Global non-secret
settings live in `~/.identark/config.toml`.

```bash
identark config show
identark config set project_name "My Agent"
identark config get project_name
identark config set --global api_url https://api.identark.io
```

Config commands protect token fields from generic `get` and `set` access. API
URLs must use HTTPS, except `http://localhost` for local development.

## Environment variables

| Variable | Purpose |
| --- | --- |
| `IDENTARK_API_KEY` | Preferred non-persisted scoped API key |
| `IDENTARK_SESSION_TOKEN` | Non-persisted session token |
| `IDENTARK_TOKEN` | Legacy non-persisted token alias |
| `IDENTARK_API_URL` | Override the API endpoint for a command |
| `IDENTARK_DISABLE_KEYRING` | Force the warned `0600` file fallback |
| `IDENTARK_DEBUG` | Enable child-process debug mode |

Token precedence is the order shown above.

## Development and release gates

```bash
uv sync --locked --extra dev
uv run ruff format --check identark_cli tests scripts
uv run ruff check identark_cli tests scripts
uv run mypy identark_cli
uv run pytest
uv build
uv run python scripts/check_distribution.py dist/*
```

CI runs those gates on Python 3.11 and 3.13, enforces at least 50% statement
coverage, builds both distributions, and installs the wheel into a clean virtual
environment. Releases use tags such as `v0.1.0` and PyPI Trusted Publishing;
the tag must match `identark_cli.__version__`.

Before the first release, configure a pending PyPI Trusted Publisher for:

- PyPI project: `identark-cli`
- GitHub repository: `identark/identark-cli`
- Workflow: `publish.yml`
- Environment: `pypi`

## Contributing

Contributions are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md) for
local setup, the public/private boundary, and the required verification checks.
Please follow the [Code of Conduct](CODE_OF_CONDUCT.md), use the
[support channels](SUPPORT.md) for questions, and report vulnerabilities only
through the private process in [SECURITY.md](SECURITY.md).

## Support and license

- Documentation: <https://docs.identark.io/cli>
- Issues: <https://github.com/identark/identark-cli/issues>
- Email: support@identark.io

Licensed under the MIT License. See `LICENSE`.
