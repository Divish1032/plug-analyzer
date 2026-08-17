from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
import zarr

from plug_analyzer.large_pipeline import inspect_large_analysis, run_large_analysis
from plug_analyzer.pipeline import (
    PipelineConfig,
    PipelineMasks,
    RobustnessMode,
    run_analysis,
)


def _fixture() -> tuple[np.ndarray, PipelineMasks, PipelineConfig]:
    rng = np.random.default_rng(20260814)
    shape = (7, 13, 19)
    raw = np.rint(100 + rng.normal(0, 4, shape)).astype(np.uint16)
    z, y, x = np.indices(shape)
    plug_signal = (x >= 3) & (x <= 16) & (((y - 6.5) / 3.0) ** 2 + ((z - 3.0) / 3.5) ** 2 < 1.0)
    # This one continuous component crosses every deliberately awkward chunk seam.
    raw[plug_signal] += 80
    background = np.zeros(shape, dtype=np.bool_)
    background[:, :3, :] = True
    analysis = np.ones(shape, dtype=np.bool_)
    lumen = np.ones(shape, dtype=np.bool_)
    envelope = np.zeros(shape, dtype=np.bool_)
    envelope[:, 3:11, 2:18] = True
    masks = PipelineMasks(
        background=background,
        analysis=analysis,
        lumen=lumen,
        envelope=envelope,
        geometry_source="test-reviewed-mask",
    )
    config = PipelineConfig(
        spacing_zyx_um=(0.7, 0.5, 0.5),
        filter_sigma_um=0.8,
        low_noise_multiplier=2.0,
        high_noise_multiplier=4.0,
        minimum_component_volume_um3=0.5,
        min_reference_pixels_per_plane=20,
        robustness_mode=RobustnessMode.OFF,
    )
    return raw, masks, config


def _cached(path: Path, data: np.ndarray) -> zarr.Array:
    array = zarr.open_array(
        path,
        mode="w",
        shape=data.shape,
        chunks=(2, 5, 6),
        dtype=data.dtype,
        zarr_format=3,
    )
    array[:] = data
    return array


def _cached_masks(path: Path, masks: PipelineMasks) -> PipelineMasks:
    path.mkdir()
    stored: dict[str, zarr.Array | None] = {}
    for name in ("background", "analysis", "lumen", "envelope"):
        source = getattr(masks, name)
        if source is None:
            stored[name] = None
            continue
        array = zarr.open_array(
            path / f"{name}.zarr",
            mode="w",
            shape=source.shape,
            chunks=(2, 5, 6),
            dtype="bool",
            zarr_format=3,
        )
        array[:] = source
        stored[name] = array
    return PipelineMasks(
        background=stored["background"],  # type: ignore[arg-type]
        analysis=stored["analysis"],  # type: ignore[arg-type]
        lumen=stored["lumen"],  # type: ignore[arg-type]
        envelope=stored["envelope"],  # type: ignore[arg-type]
        geometry_source=masks.geometry_source,
    )


def test_out_of_core_matches_reference_mask_and_metrics(tmp_path: Path) -> None:
    raw, masks, config = _fixture()
    reference = run_analysis(raw, masks=masks, config=config)
    cached = _cached(tmp_path / "input.zarr", raw)
    disk_masks = _cached_masks(tmp_path / "masks", masks)

    actual = run_large_analysis(
        cached,
        masks=disk_masks,
        config=config,
        workspace_directory=tmp_path / "analysis",
        chunk_shape_zyx=(2, 5, 6),
    )

    # Bit-equivalent correction, haloed filtering, and globally reconciled mask.
    np.testing.assert_array_equal(np.asarray(actual.corrected), reference.corrected)
    np.testing.assert_array_equal(np.asarray(actual.filtered), reference.filtered)
    np.testing.assert_array_equal(np.asarray(actual.plug_mask), reference.plug_mask)
    assert actual.thresholds == reference.thresholds
    assert actual.raw_background_sigma == reference.raw_background_sigma
    assert actual.filtered_background_sigma == reference.filtered_background_sigma
    np.testing.assert_array_equal(actual.background_offsets_by_z, reference.background_offsets_by_z)

    np.testing.assert_array_equal(actual.per_plane.voxel_count, reference.per_plane.voxel_count)
    np.testing.assert_array_equal(actual.per_plane.area_um2, reference.per_plane.area_um2)
    np.testing.assert_array_equal(
        actual.per_plane.corrected_integrated_intensity_au,
        reference.per_plane.corrected_integrated_intensity_au,
    )
    assert actual.volume.observed_volume_um3 == reference.volume.observed_volume_um3
    assert (
        actual.volume.fluorescence_volume_integral_au_um3
        == reference.volume.fluorescence_volume_integral_au_um3
    )
    np.testing.assert_array_equal(
        actual.volume.plane_thicknesses_um, reference.volume.plane_thicknesses_um
    )
    assert actual.axial == reference.axial
    np.testing.assert_allclose(
        actual.cross_section.plug_area_um2,
        reference.cross_section.plug_area_um2,
        rtol=0,
        atol=1e-11,
    )
    np.testing.assert_allclose(
        actual.cross_section.lumen_area_um2,
        reference.cross_section.lumen_area_um2,
        rtol=0,
        atol=5e-12,
    )
    np.testing.assert_allclose(
        actual.cross_section.occlusion_percent,
        reference.cross_section.occlusion_percent,
        rtol=0,
        atol=1e-11,
    )
    assert actual.open_path == reference.open_path
    assert actual.apparent_low_fluorescence == reference.apparent_low_fluorescence
    assert actual.boundary == reference.boundary
    assert actual.saturation.fraction == reference.saturation.fraction
    assert actual.saturation.saturated_count == reference.saturation.saturated_count

    # Disk-backed EDT plus connectivity-threshold search preserves the exact bottleneck value.
    assert actual.bottleneck_clearance.bottleneck_diameter_um == pytest.approx(
        reference.bottleneck_clearance.bottleneck_diameter_um
    )
    assert actual.bottleneck_clearance.connected == reference.bottleneck_clearance.connected
    assert "Exact disk-backed EDT" in actual.bottleneck_clearance.qualification
    summary = actual.summary_dict()
    assert summary["execution_mode"] == "out-of-core-exact-candidate"
    assert "saturated_mask" not in summary["qc"]["saturation"]


def test_preflight_inventory_is_deterministic_and_checks_disk(tmp_path: Path) -> None:
    raw, _masks, config = _fixture()
    cached = _cached(tmp_path / "input.zarr", raw)
    first = inspect_large_analysis(
        cached,
        config=config,
        workspace_parent=tmp_path,
        chunk_shape_zyx=(2, 5, 6),
    )
    second = inspect_large_analysis(
        cached,
        config=config,
        workspace_parent=tmp_path,
        chunk_shape_zyx=(2, 5, 6),
    )
    assert first.shape_zyx == raw.shape
    assert first.source_bytes == raw.nbytes
    assert first.chunk_shape_zyx == (2, 5, 6)
    assert first.gaussian_halo_zyx == second.gaussian_halo_zyx
    assert first.estimated_peak_ram_bytes == second.estimated_peak_ram_bytes
    assert first.estimated_workspace_bytes == second.estimated_workspace_bytes
    assert first.disk_safe


def test_standard_robustness_variants_match_reference(tmp_path: Path) -> None:
    raw, masks, base_config = _fixture()
    config = replace(base_config, robustness_mode=RobustnessMode.STANDARD)
    reference = run_analysis(raw, masks=masks, config=config)
    cached = _cached(tmp_path / "input.zarr", raw)
    actual = run_large_analysis(
        cached,
        masks=masks,
        config=config,
        workspace_directory=tmp_path / "analysis",
        chunk_shape_zyx=(2, 5, 6),
    )
    assert actual.variant_metrics == reference.variant_metrics
    assert actual.robustness == reference.robustness


def test_non_cardinal_axis_is_rejected_instead_of_reinterpreted(tmp_path: Path) -> None:
    raw, masks, config = _fixture()
    cached = _cached(tmp_path / "input.zarr", raw)
    diagonal = replace(config, axis_zyx=(0.0, 1.0, 1.0))
    with pytest.raises(NotImplementedError, match="cardinal X"):
        run_large_analysis(
            cached,
            masks=masks,
            config=diagonal,
            workspace_directory=tmp_path / "analysis",
        )
