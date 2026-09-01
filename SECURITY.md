# Security policy

## Reporting a vulnerability

Do not report vulnerabilities through public GitHub issues, pull requests,
discussions, or social media. Email **security@identark.io** with:

- the affected CLI version;
- a concise description of the issue and its impact;
- reproduction steps or a proof of concept;
- any suggested mitigation;
- a safe way to contact you.

Do not include live credentials, customer data, production tokens, or sensitive
logs. Use synthetic values and redact request identifiers unless IdentArk asks
for them through a protected channel.

We aim to acknowledge complete reports within two business days, share an
initial assessment within seven days, and coordinate remediation and disclosure
based on severity. Complex issues may take longer; we will keep reporters
informed when possible. Please allow a reasonable remediation window before
public disclosure.

## Supported versions

The CLI is currently alpha software. Security fixes are applied to the latest
released version. Users should upgrade promptly after a security release.

| Version | Supported |
|---|---|
| Latest released version | Yes |
| Unreleased source code | Best effort |
| Older releases | No |

## Security model

The CLI is an untrusted network client. It does not enforce the control plane's
authorization, credential, risk, approval, or audit policies. Those decisions
remain server-side.

The CLI may temporarily handle sensitive values for explicit local-development
or credential-submission flows. It must not log or print them. Device-login
tokens are stored in the OS keychain when available; the documented mode-`0600`
file fallback is weaker because other processes running as the same OS user can
read it.

The published CLI distribution must contain only the allowlisted public package
surface and must never import private control-plane modules. CI inspects built
archives before release.

## Coordinated disclosure

Do not access data that is not yours, degrade service, persist access, or move
laterally while researching. We will coordinate a disclosure date, credit
preferences, and a security advisory when appropriate.
