#!/usr/bin/env python3
"""Create and verify checksummed Plug Analyzer release metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import tomllib
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path

SUPPORTED_PLATFORMS = {
    "macos-arm64": ".dmg",
    "windows-x64": "-Setup.exe",
}
REQUIRED_SUPPORT_FILES = (
    "THIRD_PARTY_NOTICES.md",
    "CLEAN_MACHINE_SMOKE_CHECKLIST.md",
)


class VerificationError(RuntimeError):
    """A release artifact is missing, inconsistent, or corrupted."""


def project_version(project_root: Path) -> str:
    pyproject_path = project_root / "pyproject.toml"
    try:
        with pyproject_path.open("rb") as stream:
            return str(tomllib.load(stream)["project"]["version"])
    except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        raise VerificationError(
            f"cannot read project version from {pyproject_path}: {exc}"
        ) from exc


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def expected_artifact_name(version: str, target_platform: str) -> str:
    suffix = SUPPORTED_PLATFORMS[target_platform]
    return f"Plug-Analyzer-{version}-{target_platform}{suffix}"


def _atomic_text(path: Path, contents: str) -> None:
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(contents)
            temporary_name = temporary.name
        os.replace(temporary_name, path)
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def _source_revision(project_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    return value or None


def write_build_info(
    *,
    project_root: Path,
    artifacts_dir: Path,
    target_platform: str,
    version: str,
    algorithm_version: str,
    protocol_version: str,
) -> dict[str, object]:
    lock_path = project_root / "uv.lock"
    if not lock_path.is_file():
        raise VerificationError(f"dependency lock is missing: {lock_path}")
    try:
        nuitka_version = package_version("nuitka")
    except PackageNotFoundError as exc:
        raise VerificationError(
            "Nuitka is missing; release metadata must identify the compiler"
        ) from exc
    build_info: dict[str, object] = {
        "schema_version": 1,
        "app_version": version,
        "algorithm_version": algorithm_version,
        "protocol_version": protocol_version,
        "target_platform": target_platform,
        "source_revision": _source_revision(project_root),
        "dependency_lock_sha256": sha256(lock_path),
        "build_python": platform.python_version(),
        "build_tool": {"name": "Nuitka", "version": nuitka_version},
        "created_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
    _atomic_text(
        artifacts_dir / "BUILD_INFO.json",
        json.dumps(build_info, indent=2, sort_keys=True) + "\n",
    )
    return build_info


def create_metadata(
    *,
    project_root: Path,
    artifacts_dir: Path,
    target_platform: str,
    version: str,
    algorithm_version: str,
    protocol_version: str,
) -> None:
    artifact_name = expected_artifact_name(version, target_platform)
    tracked_names = [artifact_name, *REQUIRED_SUPPORT_FILES]
    for name in tracked_names:
        path = artifacts_dir / name
        if not path.is_file() or path.stat().st_size == 0:
            raise VerificationError(f"required non-empty release file is missing: {path}")

    build_info_path = artifacts_dir / "BUILD_INFO.json"
    if build_info_path.exists():
        build_info = _read_json(build_info_path)
        expected = {
            "app_version": version,
            "algorithm_version": algorithm_version,
            "protocol_version": protocol_version,
            "target_platform": target_platform,
        }
        for key, expected_value in expected.items():
            if build_info.get(key) != expected_value:
                raise VerificationError(
                    f"existing BUILD_INFO.json has {key}={build_info.get(key)!r}; "
                    f"expected {expected_value!r}"
                )
    else:
        write_build_info(
            project_root=project_root,
            artifacts_dir=artifacts_dir,
            target_platform=target_platform,
            version=version,
            algorithm_version=algorithm_version,
            protocol_version=protocol_version,
        )
    tracked_names.append("BUILD_INFO.json")
    checksums = {name: sha256(artifacts_dir / name) for name in tracked_names}
    checksum_text = "".join(f"{checksums[name]}  {name}\n" for name in sorted(checksums))
    _atomic_text(artifacts_dir / "SHA256SUMS.txt", checksum_text)

    manifest = {
        "schema_version": 1,
        "app_version": version,
        "algorithm_version": algorithm_version,
        "protocol_version": protocol_version,
        "target_platform": target_platform,
        "artifact": {
            "filename": artifact_name,
            "sha256": checksums[artifact_name],
            "size_bytes": (artifacts_dir / artifact_name).stat().st_size,
        },
        "files": [{"filename": name, "sha256": checksums[name]} for name in sorted(checksums)],
    }
    _atomic_text(
        artifacts_dir / "release-manifest.json",
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    )


def _read_json(path: Path) -> dict[str, object]:
    try:
        with path.open(encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"expected a JSON object in {path}")
    return value


def _read_checksum_file(path: Path) -> dict[str, str]:
    checksums: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise VerificationError(f"cannot read {path}: {exc}") from exc
    for line_number, line in enumerate(lines, 1):
        digest, separator, filename = line.partition("  ")
        if not separator or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise VerificationError(f"malformed checksum line {line_number} in {path}")
        if not filename or Path(filename).name != filename:
            raise VerificationError(f"unsafe checksum filename on line {line_number}: {filename!r}")
        if filename in checksums:
            raise VerificationError(f"duplicate checksum entry: {filename}")
        checksums[filename] = digest
    return checksums


def _deep_platform_check(artifact: Path, target_platform: str) -> None:
    if target_platform == "macos-arm64":
        if platform.system() != "Darwin" or platform.machine() != "arm64":
            raise VerificationError("deep macOS verification requires Apple Silicon macOS")
        try:
            subprocess.run(
                ["hdiutil", "imageinfo", str(artifact)],
                check=True,
                capture_output=True,
                timeout=60,
            )
        except (FileNotFoundError, subprocess.SubprocessError) as exc:
            raise VerificationError(f"hdiutil rejected {artifact}: {exc}") from exc
    else:
        if artifact.read_bytes()[:2] != b"MZ":
            raise VerificationError(
                f"Windows installer does not have a PE executable header: {artifact}"
            )


def verify(
    *,
    project_root: Path,
    artifacts_dir: Path,
    target_platform: str,
    requested_version: str | None,
    deep: bool,
) -> None:
    declared_version = project_version(project_root)
    manifest_path = artifacts_dir / "release-manifest.json"
    checksum_path = artifacts_dir / "SHA256SUMS.txt"
    manifest = _read_json(manifest_path)
    build_info = _read_json(artifacts_dir / "BUILD_INFO.json")
    manifest_version = manifest.get("app_version")
    version = requested_version or str(manifest_version)
    if version != declared_version:
        raise VerificationError(
            f"requested/release version {version!r} does not match pyproject version {declared_version!r}"
        )
    if manifest_version != version or build_info.get("app_version") != version:
        raise VerificationError("app version is inconsistent across release metadata")
    if manifest.get("target_platform") != target_platform:
        raise VerificationError("manifest target platform does not match verification target")
    if build_info.get("target_platform") != target_platform:
        raise VerificationError("build-info target platform does not match verification target")
    for version_key in ("algorithm_version", "protocol_version"):
        if not manifest.get(version_key) or manifest.get(version_key) != build_info.get(
            version_key
        ):
            raise VerificationError(f"missing or inconsistent {version_key}")

    artifact_name = expected_artifact_name(version, target_platform)
    expected_files = {artifact_name, *REQUIRED_SUPPORT_FILES, "BUILD_INFO.json"}
    checksums = _read_checksum_file(checksum_path)
    if set(checksums) != expected_files:
        raise VerificationError(
            f"checksum inventory mismatch; expected {sorted(expected_files)}, got {sorted(checksums)}"
        )
    for filename, expected_digest in checksums.items():
        path = artifacts_dir / filename
        if not path.is_file() or path.stat().st_size == 0:
            raise VerificationError(f"checksummed file is missing or empty: {path}")
        actual_digest = sha256(path)
        if actual_digest != expected_digest:
            raise VerificationError(f"checksum mismatch for {path.name}")

    artifact_entry = manifest.get("artifact")
    if not isinstance(artifact_entry, dict):
        raise VerificationError("manifest artifact entry is missing")
    artifact_path = artifacts_dir / artifact_name
    if artifact_entry.get("filename") != artifact_name:
        raise VerificationError("manifest artifact filename is incorrect")
    if artifact_entry.get("sha256") != checksums[artifact_name]:
        raise VerificationError("manifest artifact checksum is incorrect")
    if artifact_entry.get("size_bytes") != artifact_path.stat().st_size:
        raise VerificationError("manifest artifact size is incorrect")

    manifest_files = manifest.get("files")
    if not isinstance(manifest_files, list):
        raise VerificationError("manifest file inventory is missing")
    manifest_checksums = {
        item.get("filename"): item.get("sha256")
        for item in manifest_files
        if isinstance(item, dict)
    }
    if manifest_checksums != checksums:
        raise VerificationError("manifest and SHA256SUMS inventories differ")
    if deep:
        _deep_platform_check(artifact_path, target_platform)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    default_project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--platform", choices=sorted(SUPPORTED_PLATFORMS), required=True)
    parser.add_argument("--version")
    parser.add_argument("--project-root", type=Path, default=default_project_root)
    write_group = parser.add_mutually_exclusive_group()
    write_group.add_argument("--write-build-info", action="store_true")
    write_group.add_argument("--write-manifest", action="store_true")
    parser.add_argument("--algorithm-version")
    parser.add_argument("--protocol-version")
    parser.add_argument("--deep", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    project_root = args.project_root.resolve()
    artifacts_dir = args.artifacts_dir.resolve()
    try:
        declared_version = project_version(project_root)
        requested_version = args.version or declared_version
        if requested_version != declared_version:
            raise VerificationError(
                f"--version {requested_version!r} does not match pyproject version {declared_version!r}"
            )
        if not artifacts_dir.is_dir():
            raise VerificationError(f"artifact directory does not exist: {artifacts_dir}")
        algorithm_version = args.algorithm_version or requested_version
        protocol_version = args.protocol_version or "candidate-v1-unlocked"
        if args.write_build_info:
            write_build_info(
                project_root=project_root,
                artifacts_dir=artifacts_dir,
                target_platform=args.platform,
                version=requested_version,
                algorithm_version=algorithm_version,
                protocol_version=protocol_version,
            )
            print(f"wrote embedded build information: {artifacts_dir / 'BUILD_INFO.json'}")
            return 0
        if args.write_manifest:
            create_metadata(
                project_root=project_root,
                artifacts_dir=artifacts_dir,
                target_platform=args.platform,
                version=requested_version,
                algorithm_version=algorithm_version,
                protocol_version=protocol_version,
            )
        verify(
            project_root=project_root,
            artifacts_dir=artifacts_dir,
            target_platform=args.platform,
            requested_version=requested_version,
            deep=args.deep,
        )
    except VerificationError as exc:
        print(f"release verification failed: {exc}", file=sys.stderr)
        return 2
    print(
        f"verified Plug Analyzer {requested_version} release for {args.platform}: {artifacts_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
