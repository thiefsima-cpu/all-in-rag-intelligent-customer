from __future__ import annotations

import unittest


class ModuleBoundaryFacadeTests(unittest.TestCase):
    def test_configuration_sections_package_exports_section_loaders(self) -> None:
        from rag_modules.configuration import sections

        self.assertEqual(
            set(sections.__all__),
            {
                "load_api_settings",
                "load_generation_settings",
                "load_graph_settings",
                "load_model_settings",
                "load_observability_settings",
                "load_retrieval_settings",
                "load_storage_settings",
            },
        )

    def test_runtime_artifacts_package_reexports_responsibility_modules(self) -> None:
        from rag_modules.runtime import artifacts
        from rag_modules.runtime.artifacts import (
            documents,
            manifest,
            manifest_store,
            signatures,
        )

        self.assertIs(artifacts.ArtifactManifest, manifest.ArtifactManifest)
        self.assertIs(artifacts.ArtifactManifestStore, manifest_store.ArtifactManifestStore)
        self.assertIs(artifacts.write_documents, documents.write_documents)
        self.assertIs(artifacts.compute_index_signature, signatures.compute_index_signature)

    def test_query_planner_facade_reexports_planning_service(self) -> None:
        from rag_modules.query_understanding import planner_service
        from rag_modules.query_understanding.planning import QueryPlanner

        self.assertIs(planner_service.QueryPlanner, QueryPlanner)

    def test_build_job_store_facade_reexports_build_job_components(self) -> None:
        from rag_modules.interfaces.api import build_job_store, build_jobs

        self.assertIn("BuildJobRepository", build_job_store.__all__)
        for name in build_job_store.__all__:
            self.assertIs(getattr(build_job_store, name), getattr(build_jobs, name))


if __name__ == "__main__":
    unittest.main()
