from __future__ import annotations

import importlib
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

    def test_runtime_artifacts_package_reexports_owned_storage_capabilities(self) -> None:
        from rag_modules.runtime import artifacts
        from rag_modules.runtime.artifacts import documents, manifest_store, signatures

        self.assertIs(artifacts.ArtifactManifestStore, manifest_store.ArtifactManifestStore)
        self.assertIs(artifacts.write_documents, documents.write_documents)
        self.assertIs(artifacts.compute_index_signature, signatures.compute_index_signature)
        self.assertNotIn("ArtifactManifest", artifacts.__dict__)

    def test_operational_scripts_import_canonical_contracts(self) -> None:
        importlib.import_module("scripts.smoke_answer_pipeline_real_route")
        importlib.import_module("scripts.pressure_api_service")

    def test_query_understanding_package_reexports_planning_service(self) -> None:
        import rag_modules.query_understanding as query_understanding
        from rag_modules.query_understanding.planning import QueryPlanner

        self.assertIs(query_understanding.QueryPlanner, QueryPlanner)

    def test_build_job_store_facade_reexports_build_job_components(self) -> None:
        from rag_modules.interfaces.api import build_job_store, build_jobs

        self.assertIn("BuildJobRepository", build_job_store.__all__)
        for name in build_job_store.__all__:
            self.assertIs(getattr(build_job_store, name), getattr(build_jobs, name))


if __name__ == "__main__":
    unittest.main()
