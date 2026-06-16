from __future__ import annotations

import tempfile
import unittest

from rag_modules.app.provider_components.build_pipeline import (
    DefaultBuildPipelineComponentProvider,
)
from rag_modules.build_pipeline import (
    DocumentArtifactBuildService,
    SemanticGraphSchemaSyncService,
)
from rag_modules.configuration.testing import build_test_config


class BuildPipelineProviderTests(unittest.TestCase):
    def test_provider_exposes_build_pipeline_services(self) -> None:
        provider = DefaultBuildPipelineComponentProvider()
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_test_config(
                {
                    "storage": {
                        "index_cache_dir": temp_dir,
                        "artifact_manifest_path": f"{temp_dir}/artifact_manifest.json",
                    }
                }
            )

            document_builder = provider.provide_document_artifact_builder(config=config)
            schema_sync = provider.provide_semantic_graph_schema_sync(
                config=config,
                neo4j_manager=object(),
            )

        self.assertIsInstance(document_builder, DocumentArtifactBuildService)
        self.assertIsInstance(schema_sync, SemanticGraphSchemaSyncService)


if __name__ == "__main__":
    unittest.main()
