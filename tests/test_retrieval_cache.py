from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from langchain_core.documents import Document

from rag_modules.configuration.testing import build_test_config
from rag_modules.retrieval_cache import (
    HYBRID_CACHE_SCHEMA_VERSION,
    RetrievalCacheStore,
)


class RetrievalCacheStoreTests(unittest.TestCase):
    def _store(self, cache_dir: str) -> RetrievalCacheStore:
        config = build_test_config(
            {"storage": {"index_cache_dir": cache_dir}}
        )
        return RetrievalCacheStore(config)

    def test_json_cache_round_trip_and_full_chunk_signature(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            chunks = [
                Document(
                    page_content=f"chunk-{index}",
                    metadata={"chunk_id": str(index), "nested": {"value": index}},
                )
                for index in range(25)
            ]
            payload = {
                "graph_index_version": 3,
                "entity_kv_store": {},
                "relation_kv_store": {},
            }

            store.save(chunks, payload)
            loaded = store.load(chunks)
            changed_chunks = list(chunks)
            changed_chunks[-1] = Document(
                page_content="changed-final-chunk",
                metadata=chunks[-1].metadata,
            )

            self.assertEqual(loaded, payload)
            self.assertIsNone(store.load(changed_chunks))
            self.assertTrue(store.path().endswith("hybrid_index.json"))
            envelope = json.loads(Path(store.path()).read_text(encoding="utf-8"))
            self.assertEqual(
                envelope["schema_version"],
                HYBRID_CACHE_SCHEMA_VERSION,
            )

    def test_tampered_cache_payload_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            chunks = [Document(page_content="chunk", metadata={"chunk_id": "1"})]
            store.save(chunks, {"value": "original"})

            path = Path(store.path())
            envelope = json.loads(path.read_text(encoding="utf-8"))
            envelope["artifacts"]["value"] = "tampered"
            path.write_text(
                json.dumps(envelope, ensure_ascii=False),
                encoding="utf-8",
            )

            self.assertIsNone(store.load(chunks))


if __name__ == "__main__":
    unittest.main()
