from __future__ import annotations

import unittest


class ModuleBoundaryFacadeTests(unittest.TestCase):
    def test_configuration_section_loader_facade_reexports_section_loaders(self) -> None:
        from rag_modules.configuration import section_loaders, sections

        for name in section_loaders.__all__:
            self.assertIs(getattr(section_loaders, name), getattr(sections, name))

    def test_artifacts_facade_reexports_responsibility_modules(self) -> None:
        from rag_modules import (
            artifact_documents,
            artifact_manifest,
            artifact_manifest_store,
            artifact_signatures,
            artifacts,
        )

        self.assertIs(artifacts.ArtifactManifest, artifact_manifest.ArtifactManifest)
        self.assertIs(
            artifacts.ArtifactManifestStore, artifact_manifest_store.ArtifactManifestStore
        )
        self.assertIs(artifacts.write_documents, artifact_documents.write_documents)
        self.assertIs(
            artifacts.compute_index_signature, artifact_signatures.compute_index_signature
        )

    def test_query_planner_facade_reexports_planning_service(self) -> None:
        from rag_modules.query_understanding import planner_service
        from rag_modules.query_understanding.planning import QueryPlanner

        self.assertIs(planner_service.QueryPlanner, QueryPlanner)

    def test_build_job_store_facade_reexports_build_job_components(self) -> None:
        from rag_modules.interfaces.api import build_job_store, build_jobs

        for name in build_job_store.__all__:
            self.assertIs(getattr(build_job_store, name), getattr(build_jobs, name))


if __name__ == "__main__":
    unittest.main()
