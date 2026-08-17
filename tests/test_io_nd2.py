from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import dask.array as da
import numpy as np
import pytest

from plug_analyzer.io import (
    CalibrationSource,
    ND2Reader,
    SelectionError,
    SourceFormat,
    SourceReadError,
    UnsupportedFormatError,
    VolumeSelection,
    open_reader,
)
from plug_analyzer.io import nd2_reader as nd2_module


class _FakeND2File:
    data = np.arange(2 * 2 * 3 * 2 * 4 * 5, dtype=np.uint16).reshape(2, 2, 3, 2, 4, 5)

    def __init__(self, path: Path, *, validate_frames: bool = False):
        self.path = path
        self.validate_frames = validate_frames
        assert not validate_frames
        self.sizes = {"P": 2, "T": 2, "Z": 3, "C": 2, "Y": 4, "X": 5}
        self.dtype = self.data.dtype
        self.attributes = SimpleNamespace(bitsPerComponentSignificant=12)
        self.metadata = {
            "channels": [
                {"channel": {"name": "FITC"}},
                {"channel": {"name": "TRITC"}},
            ]
        }
        self.experiment = [
            {
                "type": "XYPosLoop",
                "parameters": {"points": [{"name": "A1"}, {"name": "A2"}]},
            }
        ]
        self.text_info = {"description": "synthetic ND2 adapter fixture"}

    def __enter__(self) -> _FakeND2File:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def voxel_size(self, channel: int = 0) -> SimpleNamespace:
        assert channel == 0
        return SimpleNamespace(x=0.3, y=0.4, z=0.7)

    def unstructured_metadata(self, *, strip_prefix: bool = True) -> dict[str, object]:
        assert not strip_prefix
        return {"ImageMetadataLV": {"native": "preserved"}}

    def to_dask(self, *, wrapper: bool = True, copy: bool = True) -> da.Array:
        assert wrapper and copy
        return da.from_array(self.data, chunks=(1, 1, 1, 1, 4, 5))


def test_nd2_positions_time_channels_and_lazy_region(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "source.nd2"
    path.write_bytes(b"synthetic fixture")
    monkeypatch.setattr(nd2_module.nd2, "is_supported_file", lambda _path: True)
    monkeypatch.setattr(nd2_module.nd2, "is_legacy", lambda _path: False)
    monkeypatch.setattr(nd2_module.nd2, "ND2File", _FakeND2File)

    reader = ND2Reader(path)
    info = reader.probe()
    assert info.source_format is SourceFormat.ND2
    assert info.scene_count == 2
    assert [scene.name for scene in info.scenes] == ["A1", "A2"]
    assert info.scenes[0].canonical_shape_tczyx == (2, 2, 3, 4, 5)
    assert info.scenes[0].channel_names == ("FITC", "TRITC")
    assert info.scenes[0].significant_bits == 12
    assert info.calibration.xyz_um == (0.3, 0.4, 0.7)
    assert info.calibration.z.source is CalibrationSource.NATIVE
    assert info.raw_metadata["unstructured"]["ImageMetadataLV"]["native"] == "preserved"

    selection = VolumeSelection(scene=1, time=1, channel=0, z_start=1, z_stop=3)
    region = reader.read_region(selection, (slice(None), slice(1, 4), slice(2, 5)))
    expected = _FakeND2File.data[1, 1, 1:3, 0, 1:4, 2:5]
    np.testing.assert_array_equal(region, expected)


def test_nd2_unsupported_axis_fails_closed_without_flattening(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "unsupported.nd2"
    path.write_bytes(b"synthetic fixture")

    class UnsupportedAxis(_FakeND2File):
        def __init__(self, path: Path, *, validate_frames: bool = False):
            super().__init__(path, validate_frames=validate_frames)
            self.sizes = {"Q": 2, **self.sizes}

    monkeypatch.setattr(nd2_module.nd2, "is_supported_file", lambda _path: True)
    monkeypatch.setattr(nd2_module.nd2, "is_legacy", lambda _path: False)
    monkeypatch.setattr(nd2_module.nd2, "ND2File", UnsupportedAxis)
    reader = ND2Reader(path)
    assert "Unsupported ND2 dimensions" in reader.probe().scenes[0].warnings[0]
    with pytest.raises(SelectionError, match="unsupported"):
        reader.read_plane(VolumeSelection(), 0)


def test_nd2_corrupt_metadata_and_frames_report_clear_failures(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "corrupt.nd2"
    path.write_bytes(b"synthetic corrupt fixture")

    class CorruptMetadata(_FakeND2File):
        @property
        def metadata(self):
            raise ValueError("broken metadata directory")

        @metadata.setter
        def metadata(self, _value):
            pass

    monkeypatch.setattr(nd2_module.nd2, "is_supported_file", lambda _path: True)
    monkeypatch.setattr(nd2_module.nd2, "is_legacy", lambda _path: True)
    monkeypatch.setattr(nd2_module.nd2, "ND2File", CorruptMetadata)
    with pytest.raises(SourceReadError, match="compatibility report") as captured:
        ND2Reader(path).probe()
    assert "broken metadata directory" in str(captured.value)
    assert "not reinterpreted" in str(captured.value)


def test_fake_nd2_extension_is_rejected_with_copyable_report(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "renamed.nd2"
    path.write_bytes(b"not an nd2 container")
    monkeypatch.setattr(nd2_module.nd2, "is_supported_file", lambda _path: False)
    monkeypatch.setattr(nd2_module.nd2, "is_legacy", lambda _path: False)
    with pytest.raises(UnsupportedFormatError) as captured:
        open_reader(path)
    report = captured.value.compatibility_report
    assert "Header (first 16 bytes)" in report
    assert "OME-TIFF" in report
