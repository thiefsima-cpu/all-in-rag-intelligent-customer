from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

from scripts.verify_distribution_metadata import verify_distribution_metadata


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
