# IdentArk CLI

The official CLI for [IdentArk](https://identark.io) - AI agent credential isolation.

## Overview

IdentArk CLI enables developers to:

- **Run agents with isolated credentials** - Secrets are injected at runtime, never stored in code
- **Scan for secrets** - Prevent credential leaks before they reach git
- **Approve operations from terminal** - HITL workflow without leaving your CLI
- **Manage MCP servers** - Register and manage MCP tool servers

## Installation

> **Status: not yet published.** `identark-cli` is not on PyPI and the Homebrew
> tap does not exist yet. Install from source until the first release lands.

```bash
# From a checkout of this repo
cd cloud/cli
pip install -e .
identark --version
```

Planned once published:

```bash
pip install identark-cli          # not available yet
brew install identark/tap/identark  # not available yet
```

## Quick Start

```bash
# 1. Authenticate with IdentArk
identark auth login

# 2. Initialize your project
identark init

# 3. Add credentials (stored in vault, not locally)
identark credential add OPENAI_API_KEY --ref vault://prod/openai

# 4. Scan for existing secrets
identark credential scan

# 5. Run your agent with isolated credentials
identark agent run ./my_agent.py
```

## Commands

### Authentication

```bash
identark auth login          # Authenticate with IdentArk
identark auth logout         # Log out
identark auth status         # Check authentication status
```

### Agent Development

```bash
identark agent init --name my-agent    # Initialize agent project
identark agent run ./agent.py          # Run with isolated credentials
identark agent dev --reload            # Development mode with hot reload
identark agent logs                    # View agent logs
```

### Credential Management

```bash
identark credential list                        # List configured credentials
identark credential add NAME --ref vault://...  # Add credential reference
identark credential scan                        # Scan for secrets in code
identark credential inject -- python script.py  # Run with injected credentials
```

### HITL Approvals

```bash
identark approvals list              # List pending approvals
identark approvals watch             # Watch approvals in real-time
identark approvals approve <id>      # Approve a request
identark approvals reject <id>       # Reject a request
```

### MCP Server Management

```bash
identark mcp server list             # List MCP servers
identark mcp server add              # Register new server
identark mcp server discover <id>    # Discover capabilities
identark mcp tool list --server <id> # List available tools
identark mcp tool execute --server <id> --tool <name>
```

### Configuration

```bash
identark config show                 # Show configuration
identark config set key value        # Set config value
identark config edit                 # Edit config in $EDITOR
```

## How It Works

### Credential Isolation

Instead of storing secrets in `.env` files:

```bash
# ❌ Bad: Secrets in .env
OPENAI_API_KEY=sk-abc123...
```

Use IdentArk references:

```bash
# ✅ Good: Reference to vault
identark credential add OPENAI_API_KEY --ref vault://prod/openai
```

```python
# Your code never sees the actual secret
import os
api_key = os.environ["OPENAI_API_KEY"]  # Injected at runtime
```

### Git Hook Integration

IdentArk automatically installs a pre-commit hook:

```bash
git commit -m "add feature"
✓ Scanning for secrets...
✗ Found potential secret in src/config.py:23
✗ Commit blocked. Run 'identark credential scan --fix' to resolve.
```

### HITL from Terminal

When agents need approval for high-risk operations:

```bash
$ identark approvals watch

┌─────────────────────────────────────────────┐
│ Pending Approvals (1)                       │
├─────────────────────────────────────────────┤
│ #1 delete_production_database               │
│   Risk: 95 CRITICAL                         │
│   Agent: data-cleanup-agent                 │
│   [J]ustify [A]pprove [R]eject [S]kip: A    │
└─────────────────────────────────────────────┘
✓ Approved request #1
```

## Configuration

### Project Config (`.identark/config.toml`)

```toml
version = "1"
project_name = "my-agent"
organization_id = "..."

[[credentials]]
name = "OPENAI_API_KEY"
ref = "vault://prod/openai"
required = true
```

### Global Config (`~/.identark/config.toml`)

```toml
version = "1"
api_url = "https://api.identark.io"
auto_approve_threshold = 30  # Auto-approve below this risk score
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `IDENTARK_API_URL` | IdentArk API endpoint |
| `IDENTARK_TOKEN` | Authentication token |
| `IDENTARK_DEBUG` | Enable debug logging |

## Security

- Credentials are never stored locally (only references)
- Git hooks prevent secret commits
- MFA required for high-risk approvals (risk > 70)
- All operations logged with cryptographic audit trail

## License

MIT License - see LICENSE file

## Support

- Documentation: https://docs.identark.io/cli
- Issues: https://github.com/identark/cli/issues
- Email: support@identark.io
