# Release Quality Evidence

Release success evidence is discovered only at:

`quality-evidence/releases/<package-version>/evidence-manifest.json`

Each compact manifest binds a successful integration gate and live quality gate
to the exact `evaluated_commit`, runtime profile hash, model suite, live-quality
dataset hash, active ready knowledge-base artifact summary, complete bundle
digest, and GitHub Actions artifact identity. No other path is eligible for
release-evidence discovery.

Directories outside `quality-evidence/releases/` are diagnostic history, not
release success evidence. In particular,
`live_quality_gate/20260708-203513/` is a historical failed attempt with
`case_count=0`; it must not be selected to describe current or released
quality. The historical report does not establish that current quality failed,
but it cannot support a success claim.

Only the compact `evidence-manifest.json` is committed. The complete,
deterministic quality evidence ZIP is retained as its GitHub Actions artifact
and becomes the corresponding GitHub Release asset. The authoritative verifier
checks both objects together before a protected release tag is accepted.

Do not copy credentials, raw provider payloads, customer data, or absolute
workstation paths into this directory. A manifest records safe identities,
digests, and repository-relative provenance rather than secrets or local
operator paths.
