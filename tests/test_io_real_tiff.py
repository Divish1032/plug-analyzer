from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from plug_analyzer.io import (
    CalibrationSource,
    SourceFormat,
    VolumeSelection,
    fingerprint_source,
    import_to_zarr,
    open_cached_volume,
    open_reader,
    verify_cache,
)

REAL_TIFF = Path(__file__).resolve().parents[2] / "test.tif"


@pytest.mark.integration
def test_supplied_stack_metadata_plane_read_and_temporary_cache_integrity(tmp_path: Path) -> None:
    if not REAL_TIFF.is_file():
        pytest.skip(f"supplied microscope regression stack is not present: {REAL_TIFF}")
    before = fingerprint_source(REAL_TIFF)
    reader = open_reader(REAL_TIFF)
    info = reader.probe()

    assert info.source_format is SourceFormat.IMAGEJ_TIFF
    assert info.scene_count == 1
    assert info.scenes[0].source_axes == "ZYX"
    assert info.scenes[0].canonical_shape_tczyx == (1, 1, 62, 234, 1024)
    assert info.scenes[0].dtype == np.dtype(np.uint16).str
    assert info.scenes[0].significant_bits == 12
    assert info.scenes[0].channel_names == ("FITC",)
    assert info.calibration.x.value_um == pytest.approx(0.863168, rel=1e-5)
    assert info.calibration.y.value_um == pytest.approx(0.863168, rel=1e-5)
    assert info.calibration.z.value_um == pytest.approx(0.446)
    assert info.calibration.x.source is CalibrationSource.IMAGEJ
    assert "Nikon_Confocal_Ax" in info.raw_metadata["imagej"]["Info"]

    selection = VolumeSelection()
    means = np.array([reader.read_plane(selection, z).mean() for z in range(62)])
    assert int(means.argmax()) == 18
    assert reader.read_plane(selection, 18).max() == 4095

    # The normalized copy exists only in pytest's temporary directory.
    cache = tmp_path / "real-stack-cache"
    manifest = import_to_zarr(
        reader,
        selection,
        cache,
        chunk_shape=(4, 117, 512),
    )
    assert manifest.shape_zyx == (62, 234, 1024)
    assert verify_cache(cache).valid
    cached = open_cached_volume(cache)
    for z in (0, 18, 31, 61):
        np.testing.assert_array_equal(cached[z], reader.read_plane(selection, z))

    after = fingerprint_source(REAL_TIFF)
    assert after == before
