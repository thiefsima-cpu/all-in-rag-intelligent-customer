from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_modules.configuration import ConfigProfile, default_profiles_dir, load_profile
from rag_modules.configuration.env import EnvConfigSource
from rag_modules.configuration.loader import load_config


class ConfigurationProfilesTests(unittest.TestCase):
    def test_profile_path_applies_toml_defaults_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "tiny.toml"
            profile_path.write_text(
                "\n".join(
                    [
                        "[retrieval]",
                        "top_k = 9",
                        "candidate_source_failure_threshold = 4",
                        "candidate_source_recovery_seconds = 8.5",
                        'candidate_source_degradation_strategy = "fail_fast"',
                        "",
                        "[generation]",
                        "generation_direct_max_tokens = 333",
                    ]
                ),
                encoding="utf-8",
            )

            config = load_config(
                source=EnvConfigSource(environ={}),
                profile_path=str(profile_path),
                profiles_dir=tmpdir,
            )

        self.assertEqual(config.profile_name, "tiny")
        self.assertEqual(Path(config.profile_path), profile_path.resolve())
        self.assertTrue(config.profile_hash)
        self.assertEqual(config.retrieval.top_k, 9)
        self.assertEqual(config.retrieval.candidate_source_failure_threshold, 4)
        self.assertEqual(config.retrieval.candidate_source_recovery_seconds, 8.5)
        self.assertEqual(config.retrieval.candidate_source_degradation_strategy, "fail_fast")
        self.assertEqual(config.generation.generation_direct_max_tokens, 333)

    def test_environment_overrides_profile_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "fast.toml"
            profile_path.write_text("[retrieval]\ntop_k = 3\n", encoding="utf-8")

            config = load_config(
                source=EnvConfigSource(
                    environ={
                        "GRAPH_RAG_PROFILE_PATH": str(profile_path),
                        "TOP_K": "11",
                    }
                ),
                profiles_dir=tmpdir,
            )

        self.assertEqual(config.profile_name, "fast")
        self.assertEqual(config.retrieval.top_k, 11)

    def test_base_and_named_profile_are_merged(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            profiles_dir = Path(tmpdir)
            (profiles_dir / "base.toml").write_text(
                "[generation]\nmax_tokens = 900\n",
                encoding="utf-8",
            )
            (profiles_dir / "quality.toml").write_text(
                "[retrieval]\ntop_k = 7\n",
                encoding="utf-8",
            )

            config = load_config(
                source=EnvConfigSource(environ={}),
                profile="quality",
                profiles_dir=tmpdir,
            )

        self.assertEqual(config.profile_name, "quality")
        self.assertEqual(config.retrieval.top_k, 7)
        self.assertEqual(config.generation.max_tokens, 900)

    def test_with_overrides_preserves_profile_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "dev.toml"
            profile_path.write_text("[retrieval]\ntop_k = 4\n", encoding="utf-8")
            config = load_config(
                source=EnvConfigSource(environ={}),
                profile_path=str(profile_path),
                profiles_dir=tmpdir,
            )

            updated = config.with_overrides({"retrieval": {"top_k": 8}})

        self.assertEqual(updated.profile_name, config.profile_name)
        self.assertEqual(updated.profile_path, config.profile_path)
        self.assertEqual(updated.profile_hash, config.profile_hash)
        self.assertEqual(updated.retrieval.top_k, 8)

    def test_missing_named_profile_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(FileNotFoundError):
                load_profile(profile="missing", profiles_dir=tmpdir)

    def test_profile_helpers_are_publicly_exported(self) -> None:
        self.assertEqual(default_profiles_dir().name, "profiles")
        self.assertIs(ConfigProfile, ConfigProfile)


if __name__ == "__main__":
    unittest.main()
