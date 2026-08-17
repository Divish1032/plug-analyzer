from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from plug_analyzer.exports import ExportError, export_analysis_tables, finalize_project_run
from plug_analyzer.models import (
    CalibrationSource,
    CalibrationValue,
    SourceMetadata,
    VoxelCalibration,
)
from plug_analyzer.pipeline import (
    PipelineConfig,
    RectangularRoi,
    RobustnessMode,
    masks_from_rectangles,
    run_analysis,
)
from plug_analyzer.project import ProjectStore


def _result():
    image = np.full((2, 12, 12), 10, dtype=np.uint16)
    image[:, :, :2] = 9
    image[:, :, 3:5] = 11
    image[:, 4:8, 7:10] = 100
    masks = masks_from_rectangles(
        image.shape,
        background_rois=(RectangularRoi(0, 12, 0, 5),),
        analysis_roi=RectangularRoi(0, 12, 5, 12),
        lumen_roi=RectangularRoi(0, 12, 5, 12),
    )
    return run_analysis(
        image,
        masks=masks,
        config=PipelineConfig(
            spacing_zyx_um=(1, 1, 1),
            filter_sigma_um=0,
            min_reference_pixels_per_plane=10,
            saturation_threshold=255,
            robustness_mode=RobustnessMode.OFF,
        ),
    )


def _metadata(source: Path) -> SourceMetadata:
    calibration = VoxelCalibration(
        x=CalibrationValue(value=1, source=CalibrationSource.MANUAL, confirmed=True),
        y=CalibrationValue(value=1, source=CalibrationSource.MANUAL, confirmed=True),
        z=CalibrationValue(value=1, source=CalibrationSource.MANUAL, confirmed=True),
    )
    return SourceMetadata(
        source_path=str(source),
        source_sha256="a" * 64,
        source_size_bytes=1,
        reader_name="test",
        reader_version="1",
        source_format="tiff",
        original_axes="ZYX",
        original_shape=(2, 12, 12),
        selected_shape_zyx=(2, 12, 12),
        dtype="uint16",
        calibration=calibration,
    )


def test_export_tables_are_versioned_and_do_not_overwrite(tmp_path: Path) -> None:
    result = _result()
    paths = export_analysis_tables(result, tmp_path / "export")

    assert set(paths) == {"summary_json", "per_plane_csv", "cross_section_csv"}
    payload = json.loads(paths["summary_json"].read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert "area_um2" in paths["per_plane_csv"].read_text(encoding="utf-8")
    with pytest.raises(ExportError, match="already contains"):
        export_analysis_tables(result, tmp_path / "export")


def test_finalize_project_run_saves_artifacts_and_immutable_record(tmp_path: Path) -> None:
    source = tmp_path / "source.tif"
    source.write_bytes(b"x")
    with ProjectStore.create(tmp_path / "study.plug-project", name="Study") as store:
        sample_id = store.add_sample(name="Sample", metadata=_metadata(source))
        finalized = finalize_project_run(store, sample_id=sample_id, result=_result())

        assert len(store.list_runs(sample_id)) == 1
        assert finalized.run_id
        for relative in finalized.artifacts.values():
            assert (store.paths.root / relative).is_file()
        mask = np.load(store.paths.root / finalized.artifacts["plug_mask"], allow_pickle=False)
        assert mask.dtype == np.bool_
