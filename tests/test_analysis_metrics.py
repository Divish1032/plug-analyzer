from __future__ import annotations

import numpy as np
import pytest

from plug_analyzer.analysis.metrics import (
    apparent_low_fluorescence_fraction,
    axial_extent,
    binned_cross_section_metrics,
    open_path_connectivity,
    per_plane_metrics,
    represented_plane_thicknesses_um,
    volume_metrics,
)


def test_per_plane_and_volume_metrics_have_known_signed_results() -> None:
    mask = np.zeros((2, 3, 4), dtype=np.bool_)
    mask[:, 1:3, 1:3] = True
    corrected = np.zeros(mask.shape, dtype=np.float64)
    corrected[0, mask[0]] = 2.0
    corrected[1, mask[1]] = -1.0

    planes = per_plane_metrics(
        mask,
        corrected,
        spacing_zyx_um=(2.0, 0.5, 0.25),
    )
    volume = volume_metrics(
        mask,
        corrected,
        spacing_zyx_um=(2.0, 0.5, 0.25),
    )

    np.testing.assert_array_equal(planes.voxel_count, [4, 4])
    np.testing.assert_allclose(planes.area_um2, [0.5, 0.5])
    np.testing.assert_allclose(planes.corrected_integrated_intensity_au, [8.0, -4.0])
    np.testing.assert_allclose(planes.fluorescence_area_integral_au_um2, [1.0, -0.5])
    np.testing.assert_allclose(planes.mean_corrected_intensity_au, [2.0, -1.0])
    assert volume.observed_volume_um3 == pytest.approx(2.0)
    assert volume.fluorescence_volume_integral_au_um3 == pytest.approx(1.0)


def test_empty_plane_mean_is_nan_and_other_values_are_zero() -> None:
    mask = np.zeros((2, 2, 2), dtype=np.bool_)
    mask[1, 0, 0] = True
    corrected = np.ones(mask.shape)

    result = per_plane_metrics(mask, corrected, spacing_zyx_um=(1.0, 1.0, 1.0))

    assert result.voxel_count[0] == 0
    assert result.area_um2[0] == 0.0
    assert result.corrected_integrated_intensity_au[0] == 0.0
    assert np.isnan(result.mean_corrected_intensity_au[0])


def test_nonuniform_z_positions_have_midpoint_represented_thicknesses() -> None:
    thicknesses = represented_plane_thicknesses_um((0.0, 1.0, 3.0, 6.0))

    np.testing.assert_allclose(thicknesses, [1.0, 1.5, 2.5, 3.0])
    with pytest.raises(ValueError, match="strictly increasing"):
        represented_plane_thicknesses_um((0.0, 1.0, 1.0))


def test_axial_extent_projects_physical_voxel_centers() -> None:
    mask = np.zeros((1, 1, 4), dtype=np.bool_)
    mask[0, 0, 1] = True
    mask[0, 0, 3] = True

    result = axial_extent(
        mask,
        spacing_zyx_um=(1.0, 1.0, 2.0),
        reference_point_zyx_um=(0.0, 0.0, 0.0),
        axis_zyx=(0.0, 0.0, 5.0),  # normalization is deliberate
    )

    assert result.q_min_um == pytest.approx(2.0)
    assert result.q_max_um == pytest.approx(6.0)
    assert result.q95_um == pytest.approx(5.8)


def test_binned_cross_sections_match_analytic_occlusion_curve() -> None:
    lumen = np.ones((1, 2, 3), dtype=np.bool_)
    plug = np.zeros_like(lumen)
    plug[0, 0, 0] = True
    plug[0, :, 1] = True

    result = binned_cross_section_metrics(
        plug,
        lumen,
        spacing_zyx_um=(1.0, 1.0, 1.0),
        reference_point_zyx_um=(0.0, 0.0, 0.0),
        axis_zyx=(0.0, 0.0, 1.0),
        bin_width_um=1.0,
        q_range_um=(-0.5, 2.5),
    )

    np.testing.assert_allclose(result.bin_centers_um, [0.0, 1.0, 2.0])
    np.testing.assert_allclose(result.lumen_area_um2, [2.0, 2.0, 2.0])
    np.testing.assert_allclose(result.plug_area_um2, [1.0, 2.0, 0.0])
    np.testing.assert_allclose(result.occlusion_percent, [50.0, 100.0, 0.0])
    np.testing.assert_allclose(result.open_area_um2, [1.0, 0.0, 2.0])
    assert result.maximum_occlusion_percent == 100.0
    assert result.maximum_occlusion_position_um == 1.0
    assert result.mean_occlusion_percent == 50.0
    assert result.minimum_open_area_um2 == 0.0
    assert result.minimum_open_area_position_um == 1.0


def test_open_path_reports_diagonal_only_connectivity_as_ambiguous() -> None:
    lumen = np.zeros((1, 2, 2), dtype=np.bool_)
    lumen[0, 0, 0] = True
    lumen[0, 1, 1] = True
    plug = np.zeros_like(lumen)
    inlet = np.zeros_like(lumen)
    outlet = np.zeros_like(lumen)
    inlet[0, 0, 0] = True
    outlet[0, 1, 1] = True

    result = open_path_connectivity(lumen, plug, inlet, outlet)

    assert not result.connected_6
    assert result.connected_26
    assert result.connectivity_ambiguous


def test_open_path_detects_complete_blockage() -> None:
    lumen = np.ones((1, 3, 3), dtype=np.bool_)
    plug = np.zeros_like(lumen)
    plug[:, :, 1] = True
    inlet = np.zeros_like(lumen)
    outlet = np.zeros_like(lumen)
    inlet[:, :, 0] = True
    outlet[:, :, -1] = True

    result = open_path_connectivity(lumen, plug, inlet, outlet)

    assert not result.connected_6
    assert not result.connected_26
    assert not result.connectivity_ambiguous


def test_apparent_low_fluorescence_fraction_is_physical_volume_fraction() -> None:
    lumen = np.ones((1, 2, 2), dtype=np.bool_)
    envelope = lumen.copy()
    plug = np.ones_like(lumen)
    plug[0, 1, 1] = False

    result = apparent_low_fluorescence_fraction(
        plug,
        lumen,
        envelope,
        spacing_zyx_um=(2.0, 1.0, 0.5),
    )

    assert result.percent == pytest.approx(25.0)
    assert result.low_fluorescence_volume_um3 == pytest.approx(1.0)
    assert result.envelope_lumen_volume_um3 == pytest.approx(4.0)


def test_metrics_reject_plug_voxels_outside_lumen() -> None:
    lumen = np.zeros((1, 1, 2), dtype=np.bool_)
    lumen[0, 0, 0] = True
    plug = np.zeros_like(lumen)
    plug[0, 0, 1] = True

    with pytest.raises(ValueError, match="contained"):
        binned_cross_section_metrics(
            plug,
            lumen,
            spacing_zyx_um=(1.0, 1.0, 1.0),
            reference_point_zyx_um=(0.0, 0.0, 0.0),
            axis_zyx=(0.0, 0.0, 1.0),
            bin_width_um=1.0,
        )
