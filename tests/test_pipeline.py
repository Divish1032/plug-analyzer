from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import tifffile

from plug_analyzer.models import Availability
from plug_analyzer.pipeline import (
    AnalysisCancelled,
    PipelineConfig,
    RectangularRoi,
    RobustnessMode,
    masks_from_rectangles,
    run_analysis,
)


def _known_stack() -> tuple[np.ndarray, object, PipelineConfig]:
    image = np.full((3, 20, 20), 10, dtype=np.uint16)
    # A stable, non-zero background MAD on every plane.
    image[:, :, 0:2] = 9
    image[:, :, 3:5] = 11
    image[:, 5:8, 10:14] = 100
    masks = masks_from_rectangles(
        image.shape,
        background_rois=(RectangularRoi(0, 20, 0, 5),),
        analysis_roi=RectangularRoi(0, 20, 5, 20),
        lumen_roi=RectangularRoi(0, 20, 5, 20),
        envelope_roi=RectangularRoi(5, 8, 10, 14),
    )
    config = PipelineConfig(
        spacing_zyx_um=(2.0, 1.0, 1.0),
        filter_sigma_um=0.0,
        low_noise_multiplier=2.0,
        high_noise_multiplier=4.0,
        minimum_component_volume_um3=1.0,
        min_reference_pixels_per_plane=20,
        saturation_threshold=255.0,
        robustness_mode=RobustnessMode.STANDARD,
    )
    return image, masks, config


def test_pipeline_recovers_known_area_intensity_and_volume() -> None:
    image, masks, config = _known_stack()

    result = run_analysis(image, masks=masks, config=config)

    np.testing.assert_allclose(result.per_plane.area_um2, [12.0, 12.0, 12.0])
    np.testing.assert_allclose(
        result.per_plane.corrected_integrated_intensity_au,
        [1080.0, 1080.0, 1080.0],
    )
    assert result.volume.observed_volume_um3 == pytest.approx(72.0)
    assert result.volume.fluorescence_volume_integral_au_um3 == pytest.approx(6480.0)
    assert result.apparent_low_fluorescence is not None
    assert result.apparent_low_fluorescence.percent == pytest.approx(0.0)
    assert result.open_path.connected_6
    assert set(result.robustness) == {
        "observed_volume_um3",
        "summed_corrected_integrated_intensity_au",
        "maximum_plane_area_um2",
    }


def test_pipeline_summary_is_json_serializable_and_scientifically_qualified() -> None:
    image, masks, config = _known_stack()
    result = run_analysis(image, masks=masks, config=config)

    encoded = json.dumps(result.summary_dict(), allow_nan=False)
    assert "not true porosity" not in encoded  # qualification lives in saved MetricValue
    finalized = result.to_finalized_run(sample_id="sample-1", artifacts={"mask": "runs/x.npy"})
    metric = next(
        item for item in finalized.metrics if item.name == "apparent_low_fluorescence_percent"
    )
    assert metric.availability is Availability.WARNING
    assert "not true porosity" in (metric.qualification or "")


def test_pipeline_honours_cooperative_cancellation() -> None:
    image, masks, config = _known_stack()

    with pytest.raises(AnalysisCancelled):
        run_analysis(image, masks=masks, config=config, cancelled=lambda: True)


def test_masks_reject_analysis_outside_lumen() -> None:
    image, _, config = _known_stack()
    with pytest.raises(ValueError, match="analysis mask"):
        masks = masks_from_rectangles(
            image.shape,
            background_rois=(RectangularRoi(0, 20, 0, 2),),
            analysis_roi=RectangularRoi(0, 20, 2, 20),
            lumen_roi=RectangularRoi(0, 20, 5, 20),
        )
        run_analysis(image, masks=masks, config=config)


@pytest.mark.integration
@pytest.mark.slow
def test_supplied_tiff_candidate_pipeline_regression() -> None:
    source = Path(__file__).resolve().parents[2] / "test.tif"
    if not source.is_file():
        pytest.skip("supplied microscope regression stack is not present")
    image = tifffile.imread(source)
    assert image.shape == (62, 234, 1024)
    band = image.shape[1] // 10
    masks = masks_from_rectangles(
        image.shape,
        background_rois=(
            RectangularRoi(0, band, 0, image.shape[2]),
            RectangularRoi(image.shape[1] - band, image.shape[1], 0, image.shape[2]),
        ),
    )
    config = PipelineConfig(
        spacing_zyx_um=(0.446, 0.863, 0.863),
        filter_sigma_um=0.75,
        low_noise_multiplier=2.0,
        high_noise_multiplier=4.0,
        minimum_component_volume_um3=5.0,
        min_reference_pixels_per_plane=1_000,
        saturation_threshold=4_095.0,
        robustness_mode=RobustnessMode.OFF,
    )

    result = run_analysis(image, masks=masks, config=config)

    # This is a software-regression fingerprint, not biological ground truth.
    assert int(np.count_nonzero(result.plug_mask)) == 5_205_138
    assert result.saturation.fraction == pytest.approx(0.00006953329628480839)
    assert result.per_plane.area_um2.shape == (62,)
    assert result.boundary.touches_any_boundary
