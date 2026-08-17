from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import zarr

import plug_analyzer.service as service
from plug_analyzer.exports import _atomic_numpy
from plug_analyzer.models import ResourcePlan
from plug_analyzer.pipeline import PipelineConfig, RectangularRoi, RobustnessMode


def _cached(path: Path, data: np.ndarray) -> zarr.Array:
    result = zarr.open_array(
        path,
        mode="w",
        shape=data.shape,
        chunks=(2, 5, 6),
        dtype=data.dtype,
        zarr_format=3,
    )
    result[:] = data
    return result


def _inputs(shape: tuple[int, int, int]):
    masks = service.virtual_masks_from_rectangles(
        shape,
        background_rois=(RectangularRoi(0, 3, 0, shape[2]),),
        analysis_roi=RectangularRoi(0, shape[1], 0, shape[2]),
        lumen_roi=RectangularRoi(0, shape[1], 0, shape[2]),
    )
    config = PipelineConfig(
        spacing_zyx_um=(0.7, 0.5, 0.5),
        filter_sigma_um=0,
        minimum_component_volume_um3=0,
        min_reference_pixels_per_plane=10,
        robustness_mode=RobustnessMode.OFF,
    )
    return masks, config


def _plan(*, budget: int, decoded: int) -> ResourcePlan:
    return ResourcePlan(
        decoded_bytes=decoded,
        available_memory_bytes=budget * 2,
        memory_budget_bytes=budget,
        compute_chunk_bytes=1024**2,
        worker_threads=1,
        disk_free_bytes=10**12,
        disk_required_bytes=0,
        safe_to_start=True,
    )


def test_virtual_rectangular_mask_materializes_only_requested_slice() -> None:
    shape = (100_000, 20, 30)
    mask = service.VirtualRectangularMask(
        shape,
        (RectangularRoi(3, 8, 7, 12), RectangularRoi(10, 15, 20, 25)),
    )
    block = mask[99_998:100_000, 0:12, 5:15]
    assert block.shape == (2, 12, 10)
    assert np.count_nonzero(block) == 2 * 5 * 5
    assert mask[0, 4, 8]
    assert not mask[-1, 0, 0]
    with pytest.raises(MemoryError, match="cannot be materialized"):
        np.asarray(mask)


def test_polygon_geometry_is_sliceable_and_curved() -> None:
    shape = (4, 20, 30)
    analysis = ((2.0, 2.0), (27.0, 3.0), (20.0, 17.0), (5.0, 15.0))
    masks = service.virtual_masks_from_geometry(
        shape,
        background_rois=(RectangularRoi(0, 2, 0, 30),),
        analysis_roi=RectangularRoi(0, 20, 0, 30),
        lumen_roi=RectangularRoi(0, 20, 0, 30),
        envelope_roi=None,
        analysis_polygon_xy=analysis,
    )
    selected = masks.analysis[1:3, 4:16, 4:25]
    assert selected.shape == (2, 12, 21)
    assert np.any(selected)
    assert not bool(masks.analysis[0, 0, 0])
    with pytest.raises(MemoryError):
        np.asarray(masks.analysis)


def test_auto_selection_uses_small_reference_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw = np.full((3, 12, 13), 10, dtype=np.uint16)
    raw[:, 4:9, 6:11] = 100
    cached = _cached(tmp_path / "input.zarr", raw)
    masks, config = _inputs(raw.shape)
    called = {"small": 0, "large": 0}

    def small(volume, **kwargs):
        called["small"] += 1
        assert isinstance(volume, np.ndarray)
        assert isinstance(kwargs["masks"].background, np.ndarray)
        return "small-result"

    def large(*args, **kwargs):
        called["large"] += 1
        return "large-result"

    monkeypatch.setattr(service, "run_analysis", small)
    monkeypatch.setattr(service, "run_large_analysis", large)
    monkeypatch.setattr(
        service,
        "build_resource_plan",
        lambda **kwargs: _plan(budget=10**9, decoded=raw.nbytes),
    )
    result = service.analyze_cached_volume(cached, config=config, masks=masks)
    assert result == "small-result"
    assert called == {"small": 1, "large": 0}


def test_auto_selection_requires_explicit_large_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw = np.full((3, 12, 13), 10, dtype=np.uint16)
    cached = _cached(tmp_path / "input.zarr", raw)
    masks, config = _inputs(raw.shape)
    monkeypatch.setattr(
        service,
        "build_resource_plan",
        lambda **kwargs: _plan(budget=1, decoded=raw.nbytes),
    )
    with pytest.raises(ValueError, match="workspace_directory is required"):
        service.analyze_cached_volume(cached, config=config, masks=masks)


def test_auto_selection_uses_large_path_and_forwards_safe_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw = np.full((3, 12, 13), 10, dtype=np.uint16)
    cached = _cached(tmp_path / "input.zarr", raw)
    masks, config = _inputs(raw.shape)
    workspace = tmp_path / "project" / "work" / "analysis-1"
    monkeypatch.setattr(
        service,
        "build_resource_plan",
        lambda **kwargs: _plan(budget=1, decoded=raw.nbytes),
    )
    inventory = service.inspect_large_analysis(
        cached,
        config=config,
        workspace_parent=workspace.parent,
    )
    monkeypatch.setattr(service, "inspect_large_analysis", lambda *args, **kwargs: inventory)

    def large(cached_arg, **kwargs):
        assert cached_arg is cached
        assert kwargs["masks"] is masks
        assert Path(kwargs["workspace_directory"]) == workspace
        return "large-result"

    monkeypatch.setattr(service, "run_large_analysis", large)
    result = service.analyze_cached_volume(
        cached,
        config=config,
        masks=masks,
        workspace_directory=workspace,
    )
    assert result == "large-result"


class _NoArrayZarrProxy:
    def __init__(self, source: zarr.Array) -> None:
        self.source = source
        self.shape = source.shape
        self.dtype = source.dtype
        self.reads: list[object] = []

    def __array__(self, *args, **kwargs):
        raise AssertionError("whole-array conversion is forbidden")

    def __getitem__(self, key):
        self.reads.append(key)
        return self.source[key]


def test_atomic_numpy_streams_zarr_mask_without_whole_array_conversion(tmp_path: Path) -> None:
    expected = np.indices((5, 7, 9)).sum(axis=0) % 2 == 0
    stored = _cached(tmp_path / "mask.zarr", expected)
    proxy = _NoArrayZarrProxy(stored)
    destination = tmp_path / "mask.npy"
    _atomic_numpy(destination, proxy)

    np.testing.assert_array_equal(np.load(destination, allow_pickle=False), expected)
    assert len(proxy.reads) == expected.shape[0]
    assert all(isinstance(key, int) for key in proxy.reads)


def test_preflight_disk_high_water_sums_cache_workspace_and_atomic_mask(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    shape = (10, 20, 30)
    voxel_count = int(np.prod(shape))
    decoded = voxel_count * 2

    class Scene:
        dtype = "uint16"

    class Info:
        scenes = (Scene(),)

    class Reader:
        def probe(self):
            return Info()

        def selected_shape(self, selection):
            return shape

    captured: dict[str, int] = {}

    def resource_plan(**kwargs):
        captured["required"] = kwargs["disk_required_bytes"]
        return _plan(budget=10**9, decoded=decoded)

    monkeypatch.setattr(service, "open_reader", lambda path: Reader())
    monkeypatch.setattr(service, "build_resource_plan", resource_plan)
    service.preflight_source(tmp_path / "source.tif", project_path=tmp_path)

    expected = np.ceil(
        1.20
        * (
            decoded
            + np.ceil(voxel_count * 64 * 1.30)
            + 2 * voxel_count
            + max(16 * 1024**2, decoded // 32)
        )
        + 2 * 1024**3
    )
    assert captured["required"] == expected


def test_cached_shape_preflight_does_not_require_reference_ram_fit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def resource_plan(**kwargs):
        captured.update(kwargs)
        return _plan(budget=1, decoded=kwargs["decoded_bytes"])

    monkeypatch.setattr(service, "build_resource_plan", resource_plan)
    service.preflight_cached_shape(
        (1_000, 1_000, 1_000),
        dtype=np.dtype("uint16"),
        project_path=tmp_path,
    )
    assert captured["require_in_memory_fit"] is False
    assert int(captured["disk_required_bytes"]) > int(captured["decoded_bytes"])
