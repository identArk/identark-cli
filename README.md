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
cd cloud/cli
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

After storing your provider credential in IdentArk, promote the project with
its **reference**—never the credential value:

```bash
identark promote --credential-ref vault://prod/openai
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
identark promote --credential-ref vault://prod/openai --run
```

The capability can invoke only the registered agent's session. It cannot read
or administer credentials, and it expires automatically. Re-run `promote` to
mint a fresh short-lived capability when needed.

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
uv sync --project cli --locked --extra dev
uv run --project cli ruff format --check --config cli/pyproject.toml cli/identark_cli cli/tests
uv run --project cli ruff check --config cli/pyproject.toml cli/identark_cli cli/tests
uv run --project cli mypy --config-file cli/pyproject.toml cli/identark_cli
uv run --project cli pytest cli/tests
uv build cli
```

CI runs those gates on Python 3.11 and 3.13, enforces at least 50% statement
coverage, builds both distributions, and installs the wheel into a clean virtual
environment. Releases use tags such as `cli-v0.1.0` and PyPI Trusted Publishing;
the tag must match `identark_cli.__version__`.

Before the first release, configure a pending PyPI Trusted Publisher for:

- PyPI project: `identark-cli`
- GitHub repository: `identArk/backend`
- Workflow: `cli-release.yml`
- Environment: `pypi`

## Support and license

- Documentation: <https://docs.identark.io/cli>
- Issues: <https://github.com/identArk/backend/issues>
- Email: support@identark.io

Licensed under the MIT License. See `LICENSE`.
