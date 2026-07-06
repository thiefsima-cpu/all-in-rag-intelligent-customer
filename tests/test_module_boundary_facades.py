from __future__ import annotations

import importlib
import sys
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

    def test_runtime_contract_facades_are_retired(self) -> None:
        for module_name in ("rag_modules.runtime_contracts", "rag_modules.app.runtime_contracts"):
            parent_name, attr_name = module_name.rsplit(".", 1)
            parent = importlib.import_module(parent_name)
            sys.modules.pop(module_name, None)
            if hasattr(parent, attr_name):
                delattr(parent, attr_name)

            with self.subTest(module=module_name):
                with self.assertRaises(ModuleNotFoundError):
                    importlib.import_module(module_name)

    def test_operational_scripts_import_canonical_contracts(self) -> None:
        importlib.import_module("scripts.smoke_answer_pipeline_real_route")
        importlib.import_module("scripts.pressure_api_service")
        importlib.import_module("scripts.migrate_semantic_schema")

    def test_query_understanding_package_reexports_planning_service(self) -> None:
        import rag_modules.query_understanding as query_understanding
        from rag_modules.query_understanding.planning import QueryPlanner

        self.assertIs(query_understanding.QueryPlanner, QueryPlanner)

    def test_build_job_store_facades_are_retired(self) -> None:
        for module_name in (
            "rag_modules.interfaces.api.build_job_store",
            "rag_modules.interfaces.api.build_jobs",
        ):
            parent_name, attr_name = module_name.rsplit(".", 1)
            parent = importlib.import_module(parent_name)
            sys.modules.pop(module_name, None)
            if hasattr(parent, attr_name):
                delattr(parent, attr_name)

            with self.subTest(module=module_name):
                with self.assertRaises(ModuleNotFoundError):
                    importlib.import_module(module_name)


if __name__ == "__main__":
    unittest.main()
