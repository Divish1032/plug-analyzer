import sqlite3
from pathlib import Path

import pytest

from plug_analyzer.models import (
    CalibrationSource,
    CalibrationValue,
    FinalizedRun,
    MetricValue,
    ProtocolSnapshot,
    SampleAnnotation,
    SourceMetadata,
    VoxelCalibration,
)
from plug_analyzer.project import ProjectError, ProjectLockedError, ProjectStore


def metadata() -> SourceMetadata:
    pixel = CalibrationValue(value=1.0, source=CalibrationSource.MANUAL, confirmed=True)
    return SourceMetadata(
        source_path="/input/sample.tif",
        source_sha256="a" * 64,
        source_size_bytes=64,
        reader_name="test",
        reader_version="1",
        source_format="TIFF",
        original_axes="ZYX",
        original_shape=(2, 3, 4),
        selected_shape_zyx=(2, 3, 4),
        dtype="uint16",
        calibration=VoxelCalibration(x=pixel, y=pixel, z=pixel),
    )


def test_project_roundtrip_and_immutable_runs(tmp_path: Path) -> None:
    root = tmp_path / "study.plug-project"
    with ProjectStore.create(root, name="Study") as store:
        sample_id = store.add_sample(name="A", metadata=metadata())
        run = FinalizedRun(
            run_id="run-1",
            sample_id=sample_id,
            protocol=ProtocolSnapshot(
                protocol_id="candidate",
                protocol_version="1",
                algorithm_version="0.1.0",
                parameters={"threshold": 3},
            ),
            metrics=(MetricValue(name="area", value=4, unit="micrometer^2"),),
        )
        store.save_finalized_run(run)
        with pytest.raises(sqlite3.IntegrityError):
            store.save_finalized_run(run)
        assert store.sample_metadata(sample_id) == metadata()
        assert store.list_runs(sample_id) == [run]
        annotation = SampleAnnotation(group="Control", objective="20x")
        store.set_sample_annotation(sample_id, annotation)
        assert store.sample_annotation(sample_id) == annotation

    with ProjectStore.open(root, read_only=True) as reopened:
        assert reopened.project_info()["name"] == "Study"
        assert len(reopened.list_samples()) == 1


def test_live_project_lock_prevents_second_writer(tmp_path: Path) -> None:
    root = tmp_path / "locked.plug-project"
    first = ProjectStore.create(root, name="Locked")
    try:
        with pytest.raises(ProjectLockedError):
            ProjectStore.open(root)
    finally:
        first.close()


def test_failed_schema_open_releases_writer_lock(tmp_path: Path) -> None:
    root = tmp_path / "future.plug-project"
    root.mkdir()
    database = root / "project.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA user_version = 999")

    with pytest.raises(ProjectError, match="unsupported project schema"):
        ProjectStore.open(root)

    assert not (root / ".plug-analyzer.lock").exists()


def test_v1_project_migrates_without_changing_existing_records(tmp_path: Path) -> None:
    root = tmp_path / "legacy.plug-project"
    with ProjectStore.create(root, name="Legacy") as store:
        sample_id = store.add_sample(name="A", metadata=metadata())
    with sqlite3.connect(root / "project.sqlite") as connection:
        connection.execute("DROP TABLE sample_annotations")
        connection.execute("UPDATE project SET schema_version = 1")
        connection.execute("PRAGMA user_version = 1")
    with ProjectStore.open(root) as migrated:
        assert migrated.project_info()["schema_version"] == 3
        assert migrated.sample_metadata(sample_id) == metadata()
        migrated.set_sample_annotation(sample_id, SampleAnnotation(group="Treated"))
        assert migrated.sample_annotation(sample_id).group == "Treated"
