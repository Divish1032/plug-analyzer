from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest
import tifffile

from plug_analyzer.io import (
    CacheError,
    ImportCancelled,
    VolumeSelection,
    choose_storage_chunks,
    fingerprint_source,
    import_to_zarr,
    load_cache_manifest,
    open_cached_volume,
    open_reader,
    verify_cache,
)


def _stack(path: Path) -> np.ndarray:
    data = np.arange(7 * 13 * 17, dtype=np.uint16).reshape(7, 13, 17)
    tifffile.imwrite(
        path,
        data,
        imagej=True,
        metadata={"axes": "ZYX", "spacing": 0.75, "unit": "um"},
        resolution=(5, 4),
    )
    return data


def test_lossless_cache_manifest_checksums_and_metadata(tmp_path: Path) -> None:
    source_path = tmp_path / "source.tif"
    source = _stack(source_path)
    reader = open_reader(source_path)
    cache_path = tmp_path / "project" / "data" / "sample-1"
    progress = []

    manifest = import_to_zarr(
        reader,
        VolumeSelection(z_start=1, z_stop=7),
        cache_path,
        chunk_shape=(2, 7, 9),
        progress=progress.append,
    )

    assert manifest.status == "complete"
    assert manifest.dtype == np.dtype(np.uint16).str
    assert manifest.shape_zyx == (6, 13, 17)
    assert manifest.source.sha256 == hashlib.sha256(source_path.read_bytes()).hexdigest()
    assert manifest.chunk_checksums
    assert (cache_path / "manifest.json").is_file()
    assert (cache_path / "source-metadata.json").is_file()
    assert not cache_path.with_name("sample-1.partial").exists()
    assert {event.stage for event in progress} == {"fingerprint", "import"}

    cached = open_cached_volume(cache_path)
    assert cached.dtype == source.dtype
    np.testing.assert_array_equal(cached[:], source[1:7])
    verification = verify_cache(cache_path)
    assert verification.valid
    assert verification.checked_chunks == len(manifest.chunk_checksums)
    assert not verification.errors
    assert load_cache_manifest(cache_path) == manifest


def test_cancel_keeps_resumable_partial_then_resume_finishes(tmp_path: Path) -> None:
    source_path = tmp_path / "source.tif"
    source = _stack(source_path)
    reader = open_reader(source_path)
    cache_path = tmp_path / "cache"
    import_events = 0

    def cancel_after_one_chunk() -> bool:
        return import_events >= 1

    def progress(event) -> None:
        nonlocal import_events
        if event.stage == "import" and event.completed > 0:
            import_events += 1

    with pytest.raises(ImportCancelled) as caught:
        import_to_zarr(
            reader,
            VolumeSelection(),
            cache_path,
            chunk_shape=(1, 7, 9),
            progress=progress,
            should_cancel=cancel_after_one_chunk,
        )
    partial = cache_path.with_name("cache.partial")
    assert caught.value.partial_path == partial
    assert partial.is_dir()
    assert not cache_path.exists()
    assert load_cache_manifest(partial).chunk_checksums

    manifest = import_to_zarr(
        reader,
        VolumeSelection(),
        cache_path,
        chunk_shape=(1, 7, 9),
        resume=True,
    )
    assert manifest.status == "complete"
    np.testing.assert_array_equal(open_cached_volume(cache_path)[:], source)


def test_resume_rejects_changed_selection_and_never_overwrites(tmp_path: Path) -> None:
    source_path = tmp_path / "source.tif"
    _stack(source_path)
    reader = open_reader(source_path)
    cache_path = tmp_path / "cache"

    calls = 0

    def cancellation() -> bool:
        nonlocal calls
        calls += 1
        return calls > 1

    with pytest.raises(ImportCancelled):
        import_to_zarr(
            reader,
            VolumeSelection(),
            cache_path,
            chunk_shape=(1, 13, 17),
            should_cancel=cancellation,
        )
    with pytest.raises(CacheError, match="selection"):
        import_to_zarr(
            reader,
            VolumeSelection(z_stop=6),
            cache_path,
            chunk_shape=(1, 13, 17),
        )


def test_chunk_planner_and_streaming_fingerprint(tmp_path: Path) -> None:
    chunks = choose_storage_chunks((100, 4096, 4096), np.dtype("uint16"))
    assert chunks[0] <= 8
    assert np.prod(chunks) * 2 <= 8 * 1024 * 1024

    path = tmp_path / "bytes.bin"
    payload = b"abc123" * 1000
    path.write_bytes(payload)
    progress = []
    fingerprint = fingerprint_source(path, progress=progress.append, block_bytes=127)
    assert fingerprint.sha256 == hashlib.sha256(payload).hexdigest()
    assert fingerprint.size_bytes == len(payload)
    assert progress[-1].completed == len(payload)
