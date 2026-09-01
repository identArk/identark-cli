# Release process

IdentArk CLI follows [Semantic Versioning](https://semver.org/). Only
maintainers may publish releases.

## Before tagging

1. Confirm the working tree contains only reviewed release changes.
2. Confirm `identark_cli.__version__` is the intended release version.
3. Update [CHANGELOG.md](CHANGELOG.md) with user-visible changes, migrations,
   and security notes.
4. Run the complete contribution gate:

   ```bash
   uv sync --locked --extra dev
   uv run ruff format --check identark_cli tests scripts
   uv run ruff check identark_cli tests scripts
   uv run mypy identark_cli
   uv run pytest
   uv build --out-dir /tmp/identark-cli-dist
   uv run python scripts/check_distribution.py /tmp/identark-cli-dist/*
   ```

5. Inspect both archives. They must not contain credentials, local
   configuration, caches, private control-plane code, or internal documents.
6. Install the built wheel in a clean environment and confirm `identark
   --version` works without relying on the source checkout.

## Publishing

Create an annotated `vX.Y.Z` tag from a reviewed commit and push the tag. The
`publish.yml` workflow verifies the tag, runs the release gate, builds
distributions, checks their public boundary, and publishes with PyPI Trusted
Publishing. Do not use a personal PyPI token and do not upload workstation-built
artifacts.

The `pypi` GitHub environment should require maintainer approval. The workflow
file name and environment are part of PyPI's trusted-publisher configuration and
must not be renamed without coordinating that configuration.

## After publishing

- Install the version from PyPI in a new environment and run `identark
  --version`.
- Publish GitHub release notes from the changelog.
- Confirm the PyPI project shows trusted publishing and provenance.
- If verification fails, stop promotion, document the incident, and publish a
  new patch version. PyPI releases are immutable and must not be overwritten.

## Security releases

Coordinate security releases privately according to [SECURITY.md](SECURITY.md).
Do not include exploit details until users have had a reasonable opportunity to
upgrade.
