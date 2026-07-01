from __future__ import annotations

import ast
import tomllib
import unittest
from pathlib import Path

from rag_modules.public_surface_manifest import (
    ALL_PUBLIC_SURFACE,
    CANONICAL_SURFACE,
    EXTERNAL_PUBLIC_SURFACE,
    INTERNAL_ONLY_SURFACE,
    LEGACY_PUBLIC_SURFACE,
    LEGACY_PUBLIC_SURFACE_REMOVAL_VERSION,
    LEGACY_PUBLIC_SURFACE_SCAN_RULES,
    PUBLIC_API_SURFACE,
    ROOT_PUBLIC_SURFACE,
    SERVICE_API_SURFACE,
    canonical_surface_by_module,
    legacy_surface_by_module,
    modules_for,
    public_surface_by_module,
    repo_root_facade_module_names,
    root_facade_module_names,
    surface_by_kind,
)

ROOT = Path(__file__).resolve().parents[1]
RAG_MODULES_DIR = ROOT / "rag_modules"
INTERNAL_PACKAGE_PREFIXES = tuple(modules_for(INTERNAL_ONLY_SURFACE))


def _is_within_internal_package(module_name: str) -> bool:
    return any(
        module_name == package_name or module_name.startswith(f"{package_name}.")
        for package_name in INTERNAL_PACKAGE_PREFIXES
    )


class PublicApiManifestTests(unittest.TestCase):
    def test_interfaces_package_exports_api_factories_only(self) -> None:
        import rag_modules.interfaces as interfaces

        self.assertEqual(
            set(interfaces.__all__),
            {"create_build_api_app", "create_serving_api_app"},
        )
        self.assertFalse(hasattr(interfaces, "run_qa_cli"))
        self.assertFalse(hasattr(interfaces, "build_knowledge_base_only"))

    def test_surface_entries_are_unique_and_indexed(self) -> None:
        all_modules = [entry.module_name for entry in ALL_PUBLIC_SURFACE]

        self.assertEqual(len(all_modules), len(set(all_modules)))
        self.assertEqual(set(all_modules), set(public_surface_by_module()))
        self.assertEqual(set(modules_for(CANONICAL_SURFACE)), set(canonical_surface_by_module()))
        self.assertEqual(set(modules_for(LEGACY_PUBLIC_SURFACE)), set(legacy_surface_by_module()))

    def test_surface_collections_match_declared_kind(self) -> None:
        expected_by_kind = {
            "public_api": PUBLIC_API_SURFACE,
            "service_api": SERVICE_API_SURFACE,
            "internal_only": INTERNAL_ONLY_SURFACE,
        }
        grouped = surface_by_kind()

        self.assertEqual(set(expected_by_kind), set(grouped))
        for kind, entries in expected_by_kind.items():
            self.assertEqual({kind}, {entry.kind for entry in entries})
            self.assertEqual(modules_for(entries), modules_for(grouped[kind]))

    def test_contract_kernel_is_declared_service_surface(self) -> None:
        surface = canonical_surface_by_module()

        self.assertIn("rag_modules.contracts", surface)
        self.assertEqual("service_api", surface["rag_modules.contracts"].kind)
        self.assertEqual("rag_modules.contracts", surface["rag_modules.contracts"].canonical_module)
        self.assertIn("contract kernel", surface["rag_modules.contracts"].notes)

    def test_legacy_surface_is_empty_after_final_retirement(self) -> None:
        self.assertEqual((), LEGACY_PUBLIC_SURFACE)
        self.assertEqual((), ROOT_PUBLIC_SURFACE)
        self.assertEqual((), EXTERNAL_PUBLIC_SURFACE)
        self.assertEqual({}, legacy_surface_by_module())
        self.assertEqual(frozenset(), root_facade_module_names())
        self.assertEqual(frozenset(), repo_root_facade_module_names())
        self.assertEqual("0.2.0", LEGACY_PUBLIC_SURFACE_REMOVAL_VERSION)
        self.assertEqual(
            ("internal_dependency_guard", "thin_wrapper_guard"),
            LEGACY_PUBLIC_SURFACE_SCAN_RULES,
        )

    def test_query_policy_package_data_ships_versioned_bundle_only(self) -> None:
        with (ROOT / "pyproject.toml").open("rb") as file:
            pyproject = tomllib.load(file)

        package_data = pyproject["tool"]["setuptools"]["package-data"]
        query_policy_data = tuple(package_data["rag_modules.query_policy"])

        self.assertEqual(
            (
                "resources/*/manifest.json",
                "resources/*/policy.json",
                "resources/*/prompts/*.txt",
            ),
            query_policy_data,
        )
        self.assertNotIn("defaults.json", query_policy_data)
        self.assertNotIn("planner_prompt.txt", query_policy_data)

    def test_retired_facade_class_names_are_not_package_exports(self) -> None:
        import rag_modules
        import rag_modules.app.services as app_services
        import rag_modules.generation as generation
        import rag_modules.retrieval as retrieval

        retired_exports = {
            rag_modules: {
                "GenerationIntegrationModule",
                "HybridRetrievalModule",
                "QuestionAnswerService",
            },
            app_services: {"QuestionAnswerService"},
            generation: {"GenerationIntegrationModule"},
            retrieval: {
                "HybridLegacyResultTranslator",
                "HybridRetrievalModule",
                "RetrievalResult",
            },
        }

        for module, names in retired_exports.items():
            for name in names:
                with self.subTest(module=module.__name__, name=name):
                    self.assertNotIn(name, getattr(module, "__all__", ()))
                    self.assertFalse(hasattr(module, name))

        self.assertIn("HybridRetrievalService", retrieval.__all__)
        self.assertTrue(hasattr(retrieval, "HybridRetrievalService"))

    def test_internal_only_packages_declare_internal_contract(self) -> None:
        import rag_modules.app.composition as composition
        import rag_modules.app.provider_components as provider_components

        for module in (composition, provider_components):
            self.assertTrue(getattr(module, "INTERNAL_ONLY", False))
            self.assertIn("internal", (module.__doc__ or "").lower())
            self.assertIn("instead", getattr(module, "INTERNAL_ONLY_REASON", "").lower())

    def test_non_app_code_does_not_import_internal_assembly_packages(self) -> None:
        violations: list[str] = []

        for base_dir in (RAG_MODULES_DIR, ROOT / "scripts"):
            for path in base_dir.rglob("*.py"):
                rel = path.relative_to(ROOT)
                if rel.parts[0] == "tests":
                    continue
                if rel.parts[:2] == ("rag_modules", "app"):
                    continue
                source = path.read_text(encoding="utf-8-sig")
                tree = ast.parse(source, filename=str(path))
                lines = source.splitlines()

                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if _is_within_internal_package(alias.name):
                                violations.append(
                                    f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}"
                                )
                    elif isinstance(node, ast.ImportFrom):
                        module_name = node.module or ""
                        if _is_within_internal_package(module_name):
                            violations.append(
                                f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}"
                            )

        self.assertFalse(
            violations,
            "Found non-app imports of internal assembly/provider packages:\n"
            + "\n".join(violations),
        )


if __name__ == "__main__":
    unittest.main()
