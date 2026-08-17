from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import tifffile

from plug_analyzer.io import (
    CalibrationSource,
    SelectionError,
    SourceFormat,
    TiffReader,
    UnsupportedFormatError,
    VolumeSelection,
    open_reader,
    probe_source,
)


def _imagej_hyperstack(path: Path) -> np.ndarray:
    # ImageJ dimension order is T, Z, C, Y, X.
    data = np.arange(2 * 4 * 3 * 5 * 7, dtype=np.uint16).reshape(2, 4, 3, 5, 7)
    tifffile.imwrite(
        path,
        data,
        imagej=True,
        metadata={"axes": "TZCYX", "spacing": 1.5, "unit": "um"},
        resolution=(2, 4),
    )
    return data


def test_imagej_probe_selection_and_lazy_regions(tmp_path: Path) -> None:
    path = tmp_path / "stack-with-untrusted-extension.bin"
    source = _imagej_hyperstack(path)

    reader = open_reader(path)
    assert isinstance(reader, TiffReader)
    info = reader.probe()
    assert info.source_format is SourceFormat.IMAGEJ_TIFF
    assert info.scene_count == 1
    assert info.scenes[0].source_axes == "TZCYX"
    assert info.scenes[0].canonical_shape_tczyx == (2, 3, 4, 5, 7)
    assert info.scenes[0].dtype == np.dtype(np.uint16).str
    assert info.calibration.xyz_um == pytest.approx((0.5, 0.25, 1.5))
    assert info.calibration.x.source is CalibrationSource.IMAGEJ

    selection = VolumeSelection(time=1, channel=2, z_start=1, z_stop=4)
    assert reader.selected_shape(selection) == (3, 5, 7)
    region = reader.read_region(selection, (slice(1, 3), slice(1, 4), slice(2, 6)))
    np.testing.assert_array_equal(region, source[1, 2:4, 2, 1:4, 2:6])
    np.testing.assert_array_equal(reader.read_plane(selection, 0), source[1, 1, 2])

    chunks = list(reader.iter_chunks(selection, (2, 3, 4)))
    assert len(chunks) == 8
    reconstructed = np.empty((3, 5, 7), dtype=np.uint16)
    for chunk in chunks:
        reconstructed[chunk.slices] = chunk.data
    np.testing.assert_array_equal(reconstructed, source[1, 1:4, 2])


def test_selection_fails_closed_instead_of_flattening(tmp_path: Path) -> None:
    path = tmp_path / "stack.tif"
    _imagej_hyperstack(path)
    reader = open_reader(path)

    with pytest.raises(SelectionError, match="Time index"):
        reader.selected_shape(VolumeSelection(time=2))
    with pytest.raises(SelectionError, match="Channel index"):
        reader.selected_shape(VolumeSelection(channel=3))
    with pytest.raises(SelectionError, match="Z range"):
        reader.selected_shape(VolumeSelection(z_start=3, z_stop=5))
    with pytest.raises(SelectionError, match="stride"):
        reader.read_region(
            VolumeSelection(),
            (slice(None, None, 2), slice(None), slice(None)),
        )


def test_ome_calibration_and_raw_xml_are_preserved(tmp_path: Path) -> None:
    path = tmp_path / "calibrated.ome.tif"
    data = np.arange(3 * 5 * 7, dtype=np.uint16).reshape(3, 5, 7)
    tifffile.imwrite(
        path,
        data,
        ome=True,
        photometric="minisblack",
        metadata={
            "axes": "ZYX",
            "PhysicalSizeX": 0.21,
            "PhysicalSizeXUnit": "µm",
            "PhysicalSizeY": 0.22,
            "PhysicalSizeYUnit": "µm",
            "PhysicalSizeZ": 0.8,
            "PhysicalSizeZUnit": "µm",
            "Channel": {"Name": ["FITC"]},
        },
    )

    info = probe_source(path)
    assert info.source_format is SourceFormat.OME_TIFF
    assert info.calibration.xyz_um == pytest.approx((0.21, 0.22, 0.8))
    assert info.calibration.x.source is CalibrationSource.OME
    assert info.scenes[0].channel_names == ("FITC",)
    assert isinstance(info.raw_metadata["ome_xml"], str)
    assert "PhysicalSizeX" in info.raw_metadata["ome_xml"]


def test_multipage_tiff_sequence_becomes_z_and_bigtiff_is_detected(tmp_path: Path) -> None:
    source = np.arange(5 * 6 * 7, dtype=np.uint16).reshape(5, 6, 7)
    regular = tmp_path / "sequence.tif"
    big = tmp_path / "small-bigtiff.tif"
    tifffile.imwrite(regular, source, photometric="minisblack")
    tifffile.imwrite(big, source, photometric="minisblack", bigtiff=True)

    reader = open_reader(regular)
    assert reader.probe().scenes[0].source_axes == "QYX"
    assert reader.selected_shape(VolumeSelection()) == source.shape
    np.testing.assert_array_equal(
        reader.read_region(VolumeSelection(), (slice(None), slice(None), slice(None))),
        source,
    )
    assert probe_source(big).source_format is SourceFormat.BIGTIFF


def test_invalid_nd2_has_copyable_fail_closed_diagnostic(tmp_path: Path) -> None:
    path = tmp_path / "broken.nd2"
    path.write_bytes(b"not an nd2 container")

    with pytest.raises(UnsupportedFormatError) as caught:
        open_reader(path)
    report = caught.value.compatibility_report
    assert "ND2 compatibility report" in report
    assert "not reinterpreted" in report
    assert "OME-TIFF" in report
