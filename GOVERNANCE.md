# Governance

IdentArk CLI uses a maintainer-led, consensus-seeking model. We welcome useful
contributions while protecting a security-sensitive public client and a clear
boundary from the hosted service.

## Roles

### Contributors

Anyone who opens an issue, improves documentation, reviews a change, or submits
code is a contributor.

### Reviewers

Reviewers are recurring contributors trusted to review part of the CLI. They
may recommend changes but cannot merge or publish unless they are also a
maintainer.

### Maintainers

Maintainers triage issues, approve and merge changes, manage releases, and
enforce project policies. Current maintainers and responsibilities are listed in
[MAINTAINERS.md](MAINTAINERS.md).

## Decision making

- Documentation corrections and routine fixes require one maintainer approval.
- Changes to authentication, token storage, credential handling, command output
  redaction, audit evidence, release automation, or security policy require two
  maintainer approvals when two eligible maintainers are available.
- Breaking public-command or configuration changes require a public proposal, a
  migration plan, and a major version under Semantic Versioning.
- Security fixes may be developed privately and released before public details
  are disclosed.

Maintainers seek consensus. When consensus cannot be reached, the CLI lead makes
the final decision and records the rationale in the issue or pull request.

## Protected boundary

This repository contains only the public CLI, its tests, and public
documentation. It must not contain proprietary control-plane source,
infrastructure state, credentials, customer data, or internal operational
material.

The CLI is an untrusted HTTPS client. The hosted service remains the authority
for authentication, authorisation, capability scope, policy, human approval,
and audit records. A contribution must not reproduce, weaken, or bypass those
controls.

## Becoming a maintainer

Existing maintainers may nominate a contributor who has demonstrated sustained,
constructive work, sound security judgement, and reliable reviews. Maintainer
access requires least-privilege repository permissions, two-factor
authentication, and protected environments for publishing. Inactive maintainers
may move to emeritus status after six months without project activity.
