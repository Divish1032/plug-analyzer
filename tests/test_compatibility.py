from __future__ import annotations

from plug_analyzer.compatibility import assess_run_compatibility
from plug_analyzer.models import (
    CalibrationSource,
    CalibrationValue,
    FinalizedRun,
    ProtocolSnapshot,
    SourceMetadata,
    VoxelCalibration,
)


def _source(*, channel: str = "488", pixel: float = 1.0) -> SourceMetadata:
    value = CalibrationValue(
        value=pixel,
        source=CalibrationSource.MANUAL,
        confirmed=True,
    )
    return SourceMetadata(
        source_path="/sample.tif",
        source_sha256="a" * 64,
        source_size_bytes=1,
        reader_name="test",
        reader_version="1",
        source_format="TIFF",
        original_axes="ZYX",
        original_shape=(2, 3, 4),
        selected_shape_zyx=(2, 3, 4),
        dtype="uint16",
        calibration=VoxelCalibration(x=value, y=value, z=value),
        channel_name=channel,
    )


def _run(*, threshold: float = 3.0) -> FinalizedRun:
    return FinalizedRun(
        run_id="run",
        sample_id="sample",
        protocol=ProtocolSnapshot(
            protocol_id="candidate",
            protocol_version="1",
            algorithm_version="0.1",
            parameters={
                "filter_sigma_um": 1.0,
                "low_noise_multiplier": threshold,
                "high_noise_multiplier": 5.0,
                "minimum_component_volume_um3": 1.0,
                "min_reference_pixels_per_plane": 10,
                "component_connectivity": 1,
                "cross_section_bin_width_um": 1.0,
                "robustness_mode": "validation",
                "threshold_variation": 0.1,
            },
        ),
        metrics=(),
        parameters={"reviewed_geometry": {"analysis": [0, 0, 1, 1]}},
    )


def test_compatible_runs_allow_morphology_and_intensity() -> None:
    result = assess_run_compatibility(
        _run(),
        _run(),
        left_source=_source(),
        right_source=_source(),
    )
    assert result.morphology_compatible
    assert result.intensity_compatible


def test_calibration_or_protocol_setting_warns_but_keeps_app_run_comparison() -> None:
    result = assess_run_compatibility(
        _run(),
        _run(threshold=4.0),
        left_source=_source(),
        right_source=_source(pixel=2.0),
    )
    assert result.morphology_compatible
    assert result.metric_allowed("plug volume")
    assert "can be compared" in result.summary


def test_image_channel_mismatch_blocks_only_intensity_change() -> None:
    result = assess_run_compatibility(
        _run(),
        _run(),
        left_source=_source(),
        right_source=_source(channel="561"),
    )
    assert result.morphology_compatible
    assert not result.intensity_compatible
    assert result.metric_allowed("plug volume")
    assert not result.metric_allowed("total fluorescence intensity")
