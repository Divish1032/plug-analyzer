"""Lossless, resumable import of one selected volume to a project-local Zarr cache."""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import zarr

from ._util import chunk_slices, slice_key
from .errors import CacheError, ImportCancelled
from .models import (
    CancelCallback,
    IOProgress,
    MicroscopeReader,
    ProgressCallback,
    SourceFingerprint,
    VolumeSelection,
    model_to_dict,
)

MANIFEST_VERSION = 1
ARRAY_DIRECTORY = "image.zarr"
MANIFEST_FILENAME = "manifest.json"
RAW_METADATA_FILENAME = "source-metadata.json"


@dataclass(frozen=True, slots=True)
class ChunkChecksum:
    key: str
    sha256: str
    nbytes: int
    shape: tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class CacheManifest:
    manifest_version: int
    status: str
    created_utc: str
    completed_utc: str | None
    source: SourceFingerprint
    source_name: str
    reader_id: str
    source_format: str
    selection: VolumeSelection
    shape_zyx: tuple[int, int, int]
    dtype: str
    chunks_zyx: tuple[int, int, int]
    array_directory: str
    raw_metadata_file: str
    raw_metadata_sha256: str
    calibration: dict[str, Any]
    scene: dict[str, Any]
    chunk_checksums: tuple[ChunkChecksum, ...]


@dataclass(frozen=True, slots=True)
class CacheVerification:
    valid: bool
    checked_chunks: int
    errors: tuple[str, ...]


def _emit(callback: ProgressCallback | None, progress: IOProgress) -> None:
    if callback is not None:
        callback(progress)


def _cancelled(callback: CancelCallback | None) -> bool:
    return bool(callback and callback())


def fingerprint_source(
    path: str | Path,
    *,
    progress: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
    block_bytes: int = 8 * 1024 * 1024,
) -> SourceFingerprint:
    """Calculate a streaming full-file SHA-256 without loading the file into RAM."""

    source_path = Path(path).expanduser().resolve()
    before = source_path.stat()
    digest = hashlib.sha256()
    completed = 0
    _emit(progress, IOProgress("fingerprint", 0, before.st_size, "Hashing source"))
    with source_path.open("rb") as source:
        while block := source.read(block_bytes):
            if _cancelled(should_cancel):
                raise ImportCancelled()
            digest.update(block)
            completed += len(block)
            _emit(
                progress,
                IOProgress("fingerprint", completed, before.st_size, "Hashing source"),
            )
    after = source_path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise CacheError("Source changed while its fingerprint was being calculated.")
    return SourceFingerprint("sha256", digest.hexdigest(), after.st_size, after.st_mtime_ns)


def choose_storage_chunks(
    shape_zyx: tuple[int, int, int],
    dtype: np.dtype[Any] | str,
    *,
    target_bytes: int = 8 * 1024 * 1024,
    maximum_z: int = 8,
) -> tuple[int, int, int]:
    """Choose shallow-Z chunks bounded near the 4-16 MiB plan target."""

    if len(shape_zyx) != 3 or any(size <= 0 for size in shape_zyx):
        raise ValueError("A cache shape must contain three positive ZYX dimensions.")
    itemsize = np.dtype(dtype).itemsize
    z, y, x = 1, shape_zyx[1], shape_zyx[2]
    while z * y * x * itemsize > target_bytes and (y > 1 or x > 1):
        if x >= y and x > 1:
            x = max(1, math.ceil(x / 2))
        elif y > 1:
            y = max(1, math.ceil(y / 2))
    while z < min(maximum_z, shape_zyx[0]) and (z + 1) * y * x * itemsize <= target_bytes:
        z += 1
    return z, y, x


def _array_bytes(array: np.ndarray[Any, Any]) -> bytes:
    return np.ascontiguousarray(array).tobytes(order="C")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _region_from_key(key: str) -> tuple[slice, slice, slice]:
    try:
        region = tuple(
            slice(int(part.split(":")[0]), int(part.split(":")[1])) for part in key.split(",")
        )
    except (ValueError, IndexError) as exc:
        raise CacheError(f"Invalid chunk key {key!r} in cache manifest.") from exc
    if len(region) != 3:
        raise CacheError(f"Invalid non-ZYX chunk key {key!r} in cache manifest.")
    return region  # type: ignore[return-value]


def _atomic_json(path: Path, payload: Any) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _manifest_dict(manifest: CacheManifest) -> dict[str, Any]:
    return model_to_dict(manifest)


def _load_manifest(path: Path) -> CacheManifest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return CacheManifest(
            manifest_version=int(payload["manifest_version"]),
            status=str(payload["status"]),
            created_utc=str(payload["created_utc"]),
            completed_utc=payload.get("completed_utc"),
            source=SourceFingerprint(**payload["source"]),
            source_name=str(payload["source_name"]),
            reader_id=str(payload["reader_id"]),
            source_format=str(payload["source_format"]),
            selection=VolumeSelection(**payload["selection"]),
            shape_zyx=tuple(int(item) for item in payload["shape_zyx"]),
            dtype=str(payload["dtype"]),
            chunks_zyx=tuple(int(item) for item in payload["chunks_zyx"]),
            array_directory=str(payload["array_directory"]),
            raw_metadata_file=str(payload["raw_metadata_file"]),
            raw_metadata_sha256=str(payload["raw_metadata_sha256"]),
            calibration=dict(payload["calibration"]),
            scene=dict(payload["scene"]),
            chunk_checksums=tuple(
                ChunkChecksum(
                    key=str(item["key"]),
                    sha256=str(item["sha256"]),
                    nbytes=int(item["nbytes"]),
                    shape=tuple(int(value) for value in item["shape"]),
                )
                for item in payload["chunk_checksums"]
            ),
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise CacheError(f"Cache manifest is missing or invalid: {path}: {exc}") from exc


def load_cache_manifest(cache_directory: str | Path) -> CacheManifest:
    return _load_manifest(Path(cache_directory).expanduser().resolve() / MANIFEST_FILENAME)


def open_cached_volume(cache_directory: str | Path) -> zarr.Array:
    """Open a completed normalized volume read-only."""

    cache_path = Path(cache_directory).expanduser().resolve()
    manifest = load_cache_manifest(cache_path)
    if manifest.status != "complete":
        raise CacheError(f"Cache status is {manifest.status!r}, not 'complete'.")
    return zarr.open_array(cache_path / manifest.array_directory, mode="r")


def _check_resume(
    manifest: CacheManifest,
    *,
    fingerprint: SourceFingerprint,
    reader: MicroscopeReader,
    selection: VolumeSelection,
    shape: tuple[int, int, int],
    dtype: str,
    chunks: tuple[int, int, int],
) -> None:
    mismatches: list[str] = []
    if manifest.manifest_version != MANIFEST_VERSION:
        mismatches.append("manifest version")
    if manifest.source != fingerprint:
        mismatches.append("source fingerprint")
    if manifest.reader_id != reader.reader_id:
        mismatches.append("reader")
    if manifest.selection != selection:
        mismatches.append("selection")
    if manifest.shape_zyx != shape:
        mismatches.append("shape")
    if manifest.dtype != dtype:
        mismatches.append("dtype")
    if manifest.chunks_zyx != chunks:
        mismatches.append("chunk plan")
    if mismatches:
        raise CacheError(
            "Partial import cannot be resumed because these changed: " + ", ".join(mismatches)
        )


def import_to_zarr(
    reader: MicroscopeReader,
    selection: VolumeSelection,
    cache_directory: str | Path,
    *,
    chunk_shape: tuple[int, int, int] | None = None,
    progress: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
    resume: bool = True,
    verify_writes: bool = True,
) -> CacheManifest:
    """Import all selected voxels losslessly, then atomically publish the cache.

    Work is written to ``<cache>.partial``.  Cancellation keeps that directory and
    its completed-chunk manifest so a matching call can resume safely.
    """

    target = Path(cache_directory).expanduser().resolve()
    partial = target.with_name(f"{target.name}.partial")
    if target.exists():
        raise CacheError(f"Cache destination already exists and will not be overwritten: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)

    info = reader.probe()
    shape = reader.selected_shape(selection)
    scene = info.scenes[selection.scene]
    dtype = np.dtype(scene.dtype)
    fingerprint = fingerprint_source(reader.path, progress=progress, should_cancel=should_cancel)

    existing: CacheManifest | None = None
    if partial.exists():
        if not resume:
            raise CacheError(f"Partial import already exists: {partial}")
        existing = _load_manifest(partial / MANIFEST_FILENAME)
        chunks = existing.chunks_zyx if chunk_shape is None else tuple(chunk_shape)
        _check_resume(
            existing,
            fingerprint=fingerprint,
            reader=reader,
            selection=selection,
            shape=shape,
            dtype=dtype.str,
            chunks=chunks,
        )
        array = zarr.open_array(partial / existing.array_directory, mode="r+")
        checksums = {item.key: item for item in existing.chunk_checksums}
        manifest = existing
    else:
        chunks = tuple(chunk_shape or choose_storage_chunks(shape, dtype))
        if len(chunks) != 3 or any(size <= 0 for size in chunks):
            raise CacheError("Chunk shape must contain three positive ZYX dimensions.")
        partial.mkdir()
        raw_payload = json.dumps(
            model_to_dict(info.raw_metadata), indent=2, sort_keys=True, ensure_ascii=False
        ).encode("utf-8")
        (partial / RAW_METADATA_FILENAME).write_bytes(raw_payload + b"\n")
        raw_hash = _sha256_bytes(raw_payload + b"\n")
        array = zarr.open_array(
            partial / ARRAY_DIRECTORY,
            mode="w",
            shape=shape,
            chunks=chunks,
            dtype=dtype,
            zarr_format=3,
            dimension_names=("z", "y", "x"),
            attributes={
                "axes": ["z", "y", "x"],
                "original_dtype": dtype.str,
                "selection": model_to_dict(selection),
                "calibration": model_to_dict(info.calibration),
                "source_sha256": fingerprint.sha256,
            },
        )
        checksums: dict[str, ChunkChecksum] = {}
        manifest = CacheManifest(
            manifest_version=MANIFEST_VERSION,
            status="importing",
            created_utc=datetime.now(UTC).isoformat(),
            completed_utc=None,
            source=fingerprint,
            source_name=reader.path.name,
            reader_id=reader.reader_id,
            source_format=info.source_format.value,
            selection=selection,
            shape_zyx=shape,
            dtype=dtype.str,
            chunks_zyx=chunks,
            array_directory=ARRAY_DIRECTORY,
            raw_metadata_file=RAW_METADATA_FILENAME,
            raw_metadata_sha256=raw_hash,
            calibration=model_to_dict(info.calibration),
            scene=model_to_dict(scene),
            chunk_checksums=(),
        )
        _atomic_json(partial / MANIFEST_FILENAME, _manifest_dict(manifest))

    regions = tuple(chunk_slices(shape, chunks))
    expected_keys = {slice_key(region) for region in regions}
    unexpected_keys = set(checksums) - expected_keys
    if unexpected_keys:
        raise CacheError(
            "Partial import has unexpected chunk keys: " + ", ".join(sorted(unexpected_keys))
        )
    if existing is not None:
        if tuple(array.shape) != shape or np.dtype(array.dtype) != dtype:
            raise CacheError("Partial Zarr array shape or dtype no longer matches its manifest.")
        metadata_path = partial / existing.raw_metadata_file
        if (
            not metadata_path.is_file()
            or _sha256_bytes(metadata_path.read_bytes()) != existing.raw_metadata_sha256
        ):
            raise CacheError("Partial raw source metadata checksum does not match its manifest.")
        for key, item in checksums.items():
            stored = np.asarray(array[_region_from_key(key)])
            if (
                stored.shape != item.shape
                or stored.nbytes != item.nbytes
                or _sha256_bytes(_array_bytes(stored)) != item.sha256
            ):
                raise CacheError(f"Partial chunk {key} failed resume-time integrity verification.")
    total_voxels = math.prod(shape)
    completed_voxels = sum(math.prod(item.shape) for item in checksums.values())
    _emit(progress, IOProgress("import", completed_voxels, total_voxels, "Importing voxels"))

    for region in regions:
        key = slice_key(region)
        if key in checksums:
            continue
        if _cancelled(should_cancel):
            raise ImportCancelled(partial)
        data = np.asarray(reader.read_region(selection, region))
        if data.dtype != dtype:
            raise CacheError(
                f"Reader dtype changed from {dtype.str} to {data.dtype.str} during import."
            )
        expected_shape = tuple(item.stop - item.start for item in region)
        if data.shape != expected_shape:
            raise CacheError(
                f"Reader chunk {key} has shape {data.shape}, expected {expected_shape}."
            )
        payload = _array_bytes(data)
        checksum = _sha256_bytes(payload)
        array[region] = data
        if verify_writes:
            stored = np.asarray(array[region])
            if (
                stored.dtype != dtype
                or stored.shape != data.shape
                or not np.array_equal(stored, data)
            ):
                raise CacheError(
                    f"Bit/value fidelity check failed immediately after writing chunk {key}."
                )
            if _sha256_bytes(_array_bytes(stored)) != checksum:
                raise CacheError(
                    f"Checksum fidelity check failed immediately after writing chunk {key}."
                )
        item = ChunkChecksum(key, checksum, len(payload), data.shape)
        checksums[key] = item
        completed_voxels += data.size
        manifest = replace(
            manifest,
            chunk_checksums=tuple(checksums[key] for key in sorted(checksums)),
        )
        _atomic_json(partial / MANIFEST_FILENAME, _manifest_dict(manifest))
        _emit(
            progress,
            IOProgress("import", completed_voxels, total_voxels, f"Imported chunk {key}"),
        )

    current = reader.path.stat()
    if (current.st_size, current.st_mtime_ns) != (fingerprint.size_bytes, fingerprint.mtime_ns):
        raise CacheError("Source changed during import; the partial cache was not published.")
    if len(checksums) != len(regions):
        raise CacheError(
            "Not every expected chunk was imported; the partial cache was not published."
        )
    manifest = replace(
        manifest,
        status="complete",
        completed_utc=datetime.now(UTC).isoformat(),
        chunk_checksums=tuple(checksums[key] for key in sorted(checksums)),
    )
    _atomic_json(partial / MANIFEST_FILENAME, _manifest_dict(manifest))
    os.replace(partial, target)
    _emit(progress, IOProgress("import", total_voxels, total_voxels, "Import complete"))
    return manifest


def verify_cache(
    cache_directory: str | Path,
    *,
    progress: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
) -> CacheVerification:
    """Read every cached chunk and validate manifest and raw-metadata checksums."""

    cache_path = Path(cache_directory).expanduser().resolve()
    manifest = load_cache_manifest(cache_path)
    errors: list[str] = []
    if manifest.manifest_version != MANIFEST_VERSION:
        errors.append(f"Unsupported manifest version {manifest.manifest_version}.")
    if manifest.status != "complete":
        errors.append(f"Cache status is {manifest.status!r}.")
    metadata_path = cache_path / manifest.raw_metadata_file
    try:
        if _sha256_bytes(metadata_path.read_bytes()) != manifest.raw_metadata_sha256:
            errors.append("Raw source metadata checksum does not match.")
    except OSError as exc:
        errors.append(f"Raw source metadata cannot be read: {exc}")

    try:
        array = zarr.open_array(cache_path / manifest.array_directory, mode="r")
    except Exception as exc:
        return CacheVerification(False, 0, (*errors, f"Zarr array cannot be opened: {exc}"))
    if tuple(array.shape) != manifest.shape_zyx:
        errors.append(f"Array shape {tuple(array.shape)} does not match {manifest.shape_zyx}.")
    if np.dtype(array.dtype).str != manifest.dtype:
        errors.append(f"Array dtype {np.dtype(array.dtype).str} does not match {manifest.dtype}.")

    expected_keys = {
        slice_key(region) for region in chunk_slices(manifest.shape_zyx, manifest.chunks_zyx)
    }
    recorded_keys = [item.key for item in manifest.chunk_checksums]
    if len(set(recorded_keys)) != len(recorded_keys):
        errors.append("Manifest contains duplicate chunk checksums.")
    missing_keys = expected_keys - set(recorded_keys)
    unexpected_keys = set(recorded_keys) - expected_keys
    if missing_keys:
        errors.append(f"Manifest is missing {len(missing_keys)} expected chunk checksum(s).")
    if unexpected_keys:
        errors.append(f"Manifest contains {len(unexpected_keys)} unexpected chunk checksum(s).")

    total = len(manifest.chunk_checksums)
    checked = 0
    _emit(progress, IOProgress("verify", 0, total, "Verifying cache"))
    for item in manifest.chunk_checksums:
        if _cancelled(should_cancel):
            raise ImportCancelled(cache_path)
        try:
            region = _region_from_key(item.key)
            data = np.asarray(array[region])
            digest = _sha256_bytes(_array_bytes(data))
            if data.shape != item.shape:
                errors.append(f"Chunk {item.key} shape is {data.shape}, expected {item.shape}.")
            if data.nbytes != item.nbytes:
                errors.append(
                    f"Chunk {item.key} byte count is {data.nbytes}, expected {item.nbytes}."
                )
            if digest != item.sha256:
                errors.append(f"Chunk {item.key} checksum does not match.")
        except Exception as exc:
            errors.append(f"Chunk {item.key} cannot be verified: {exc}")
        checked += 1
        _emit(progress, IOProgress("verify", checked, total, f"Verified chunk {item.key}"))
    return CacheVerification(not errors, checked, tuple(errors))
