# Security Policy

## Supported Versions

Security fixes are handled for the current package release line tracked by
`pyproject.toml` and the active `main` branch. Older package versions receive
fixes only when a release owner explicitly documents that support in
`CHANGELOG.md`.

## Reporting a Vulnerability

Do not open a public issue for a suspected vulnerability. Report it privately to
`@thiefsima-cpu` with:

- Affected package or API version.
- Reproduction steps or a minimal proof of concept.
- Whether credentials, customer data, prompts, traces, or generated artifacts may
  be exposed.
- Any known mitigations.

The owner should acknowledge the report within 3 business days, triage severity,
and coordinate a fix branch with the CI security gates passing before release.

## Required Security Gates

Pull requests to protected branches must pass:

- `pip-audit` against `requirements.txt` and `requirements-dev.txt`.
- Gitleaks secret scanning.
- SBOM generation for release traceability.
- The offline release gate, pytest coverage gate, Ruff, and mypy.

Real secrets, customer data, database credentials, API keys, and tokens must stay
out of the repository. Use `.env.example` for placeholders and local `.env` files
for private values.
