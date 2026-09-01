# Maintainers

## Active maintainers

| Maintainer | GitHub | Responsibility |
|---|---|---|
| Gold Okpa | [@Goldokpa](https://github.com/Goldokpa) | CLI lead, security, and releases |

Maintainer authority is defined in [GOVERNANCE.md](GOVERNANCE.md). Repository
access should follow least privilege, require two-factor authentication, and use
protected environments for publishing.

## Ownership

- `identark_cli/core/auth.py` and `identark_cli/core/secrets.py`: authentication
  and sensitive local storage.
- `identark_cli/core/audit_evidence.py`: public evidence-verification boundary.
- `identark_cli/commands/approvals.py`, `identark_cli/commands/credential.py`,
  and `identark_cli/commands/promote.py`: credential and approval flows.
- `.github/workflows/`, `scripts/check_distribution.py`, and release files:
  software supply chain.

The code ownership rules are recorded in [.github/CODEOWNERS](.github/CODEOWNERS).
