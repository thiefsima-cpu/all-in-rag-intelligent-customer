"""Verify wheel and sdist metadata versions for a release build."""

from __future__ import annotations

import argparse
import tarfile
import zipfile
from email.parser import Parser
from pathlib import Path
from typing import Sequence


def _metadata_version(text: str) -> str:
    version = Parser().parsestr(text).get("Version")
    if not version:
        raise ValueError("distribution metadata has no Version field")
    return version


def _wheel_version(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(names) != 1:
            raise ValueError(f"wheel must contain one METADATA file, found {len(names)}")
        return _metadata_version(archive.read(names[0]).decode("utf-8"))


def _sdist_version(path: Path) -> str:
    with tarfile.open(path) as archive:
        names = [name for name in archive.getnames() if name.endswith("/PKG-INFO")]
        if len(names) != 1:
            raise ValueError(f"sdist must contain one PKG-INFO file, found {len(names)}")
        extracted = archive.extractfile(names[0])
        if extracted is None:
            raise ValueError("sdist PKG-INFO is unreadable")
        return _metadata_version(extracted.read().decode("utf-8"))


def verify_distribution_metadata(directory: Path, expected_version: str) -> list[str]:
    wheels = sorted(directory.glob("*.whl"))
    sdists = sorted(directory.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        return [
            f"expected one wheel and one sdist, found wheels={len(wheels)} sdists={len(sdists)}"
        ]

    errors: list[str] = []
    wheel_version = _wheel_version(wheels[0])
    sdist_version = _sdist_version(sdists[0])
    if wheel_version != expected_version:
        errors.append(f"wheel version {wheel_version} does not match {expected_version}")
    if sdist_version != expected_version:
        errors.append(f"sdist version {sdist_version} does not match {expected_version}")
    return errors


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--expected-version", required=True)
    args = parser.parse_args(argv)

    try:
        errors = verify_distribution_metadata(args.directory, args.expected_version)
    except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as exc:
        print(str(exc))
        return 1
    if errors:
        for error in errors:
            print(error)
        return 1
    print(f"validated wheel and sdist version {args.expected_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
