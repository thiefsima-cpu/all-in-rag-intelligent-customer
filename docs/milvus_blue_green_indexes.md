# Milvus Blue-Green Indexes

The Milvus integration publishes vector indexes through a stable alias while
building data in one of two physical collections:

- Logical collection: `MILVUS_COLLECTION_NAME`, for example `cooking_knowledge`
- Stable alias: `cooking_knowledge__active`
- Blue collection: `cooking_knowledge__blue`
- Green collection: `cooking_knowledge__green`

`MILVUS_COLLECTION_ALIAS_SUFFIX` changes the alias suffix. Set
`MILVUS_BLUE_GREEN_ENABLED=false` only when an installation must retain the
legacy in-place collection behavior.

## Publish Flow

1. Load the active manifest and bind reads to its published collection.
2. Select the inactive blue or green collection.
3. Recreate and build only that inactive collection.
4. Load the collection and finish index construction.
5. Atomically switch the Milvus alias to the candidate collection.
6. Atomically publish the ready manifest.

If manifest publication fails after the alias switch, the alias is restored to
its previous target. If candidate construction fails, the active alias and
ready manifest remain unchanged.

## Manifest Files

The configured `ARTIFACT_MANIFEST_PATH` remains the stable active manifest.
Additional files are stored beside it:

- `artifact_manifest.candidate.json`: current or failed candidate build
- `artifact_manifest.versions/v000001.json`: immutable published/state history

Manifest schema v2 adds `manifest_version`, `index_version`, `published_at`,
`collection_base_name`, `collection_slot`, and `previous_collection_name`.
Serving startup uses `collection_name` as the physical source of truth and uses
the stable alias when it points to that same collection.
