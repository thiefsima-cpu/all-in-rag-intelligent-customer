from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts.verify_distribution_metadata import main, verify_distribution_metadata


def _write_wheel(path: Path, version: str) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "graph_rag_c9-0.dist-info/METADATA",
            f"Metadata-Version: 2.4\nName: graph-rag-c9\nVersion: {version}\n",
        )


def _write_sdist(path: Path, version: str) -> None:
    payload = f"Metadata-Version: 2.4\nName: graph-rag-c9\nVersion: {version}\n".encode()
    info = tarfile.TarInfo("graph_rag_c9-0/PKG-INFO")
    info.size = len(payload)
    with tarfile.open(path, "w:gz") as archive:
        archive.addfile(info, io.BytesIO(payload))


def test_distribution_metadata_matches_expected_version(tmp_path: Path) -> None:
    _write_wheel(tmp_path / "graph_rag_c9-0-py3-none-any.whl", "0.4.0rc1")
    _write_sdist(tmp_path / "graph_rag_c9-0.tar.gz", "0.4.0rc1")

    assert verify_distribution_metadata(tmp_path, "0.4.0rc1") == []


def test_distribution_metadata_reports_each_mismatch(tmp_path: Path) -> None:
    _write_wheel(tmp_path / "graph_rag_c9-0-py3-none-any.whl", "0.4.0rc2")
    _write_sdist(tmp_path / "graph_rag_c9-0.tar.gz", "0.4.0rc2")

    errors = verify_distribution_metadata(tmp_path, "0.4.0rc1")

    assert errors == [
        "wheel version 0.4.0rc2 does not match 0.4.0rc1",
        "sdist version 0.4.0rc2 does not match 0.4.0rc1",
    ]


def test_distribution_metadata_requires_one_archive_of_each_kind(tmp_path: Path) -> None:
    assert verify_distribution_metadata(tmp_path, "0.4.0rc1") == [
        "expected one wheel and one sdist, found wheels=0 sdists=0"
    ]


def test_cli_accepts_matching_archives(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write_wheel(tmp_path / "graph_rag_c9-0-py3-none-any.whl", "0.4.0rc1")
    _write_sdist(tmp_path / "graph_rag_c9-0.tar.gz", "0.4.0rc1")

    exit_code = main(["--directory", str(tmp_path), "--expected-version", "0.4.0rc1"])

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == "validated wheel and sdist version 0.4.0rc1"


def test_cli_reports_version_mismatch(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write_wheel(tmp_path / "graph_rag_c9-0-py3-none-any.whl", "0.4.0rc2")
    _write_sdist(tmp_path / "graph_rag_c9-0.tar.gz", "0.4.0rc2")

    exit_code = main(["--directory", str(tmp_path), "--expected-version", "0.4.0rc1"])

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "wheel version 0.4.0rc2 does not match 0.4.0rc1" in output
    assert "sdist version 0.4.0rc2 does not match 0.4.0rc1" in output


def test_cli_reports_malformed_wheel(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with zipfile.ZipFile(tmp_path / "graph_rag_c9-0-py3-none-any.whl", "w") as archive:
        archive.writestr("README.txt", "missing metadata")
    _write_sdist(tmp_path / "graph_rag_c9-0.tar.gz", "0.4.0rc1")

    exit_code = main(["--directory", str(tmp_path), "--expected-version", "0.4.0rc1"])

    assert exit_code == 1
    assert "wheel must contain one METADATA file, found 0" in capsys.readouterr().out


def test_cli_reports_metadata_without_version(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with zipfile.ZipFile(tmp_path / "graph_rag_c9-0-py3-none-any.whl", "w") as archive:
        archive.writestr(
            "graph_rag_c9-0.dist-info/METADATA",
            "Metadata-Version: 2.4\nName: graph-rag-c9\n",
        )
    _write_sdist(tmp_path / "graph_rag_c9-0.tar.gz", "0.4.0rc1")

    exit_code = main(["--directory", str(tmp_path), "--expected-version", "0.4.0rc1"])

    assert exit_code == 1
    assert "distribution metadata has no Version field" in capsys.readouterr().out
