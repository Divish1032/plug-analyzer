from __future__ import annotations

import numpy as np
import pytest

from plug_analyzer.analysis.clearance import widest_open_path_clearance


def test_widest_path_chooses_wider_corridor_and_physical_bottleneck() -> None:
    lumen = np.zeros((1, 9, 15), dtype=np.bool_)
    lumen[:, 1:8, :] = True
    plug = np.zeros_like(lumen)
    plug[:, 4:8, 6:9] = True
    inlet = np.zeros_like(lumen)
    outlet = np.zeros_like(lumen)
    inlet[:, :, 0] = lumen[:, :, 0]
    outlet[:, :, -1] = lumen[:, :, -1]

    result = widest_open_path_clearance(
        lumen,
        plug,
        inlet,
        outlet,
        spacing_zyx_um=(1.0, 1.0, 1.0),
    )

    assert result.connected
    assert result.bottleneck_diameter_um == pytest.approx(4.0)
    assert result.path_voxel_count >= 15
    assert np.all(result.path_mask <= (lumen & ~plug))
    assert "not a flow" in result.qualification


def test_bottleneck_reports_disconnected_when_plug_spans_lumen() -> None:
    lumen = np.ones((2, 5, 7), dtype=np.bool_)
    plug = np.zeros_like(lumen)
    plug[:, :, 3] = True
    inlet = np.zeros_like(lumen)
    outlet = np.zeros_like(lumen)
    inlet[:, :, 0] = True
    outlet[:, :, -1] = True

    result = widest_open_path_clearance(
        lumen,
        plug,
        inlet,
        outlet,
        spacing_zyx_um=(2.0, 1.0, 1.0),
    )

    assert not result.connected
    assert result.bottleneck_diameter_um is None
    assert result.path_voxel_count == 0
