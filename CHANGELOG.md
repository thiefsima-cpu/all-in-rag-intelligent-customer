# Changelog

All notable changes to GraphRAG C9 are recorded here.

This project follows the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
format and uses package versions from `pyproject.toml`.

## Unreleased

### Added

- Enterprise governance CI with pytest, coverage, Ruff, mypy, the offline release
  gate, dependency audit, secret scanning, and SBOM generation.
- CODEOWNERS coverage for public API contracts, quality corpus assets, and
  governance files.
- Security policy and release process documentation.

### Security

- Raised vulnerable runtime and development dependency pins identified by
  `pip-audit`, including `langchain-core`, `langsmith`, `starlette`, `ujson`,
  and `pip`.

## 0.3.0 - 2026-07-05

### Added

- Serving API, build API, offline release gate, integration gate, live quality
  gate, and local pressure tooling are maintained in one Python repository.
