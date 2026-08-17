from pathlib import Path

import pytest
from pydantic import ValidationError

from plug_analyzer.models import CalibrationSource, CalibrationValue, VoxelCalibration
from plug_analyzer.resources import (
    build_resource_plan,
    estimate_disk_required,
    safe_project_name,
    sha256_file,
    source_snapshot,
    source_unchanged,
)


def test_calibration_rejects_nonpositive_values() -> None:
    with pytest.raises(ValidationError):
        CalibrationValue(value=0, source=CalibrationSource.MANUAL)


def test_z_positions_must_be_strictly_increasing() -> None:
    value = CalibrationValue(value=1, source=CalibrationSource.NATIVE)
    with pytest.raises(ValidationError):
        VoxelCalibration(x=value, y=value, z=value, z_positions=(0, 1, 1))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("  Useful Project  ", "Useful Project"), ("CON", "CON_project"), ("a/b:c", "a_b_c")],
)
def test_safe_project_name_is_cross_platform(raw: str, expected: str) -> None:
    assert safe_project_name(raw) == expected


def test_fingerprint_and_source_stability(tmp_path: Path) -> None:
    path = tmp_path / "source.bin"
    path.write_bytes(b"abc")
    snapshot = source_snapshot(path)
    assert source_unchanged(path, snapshot)
    assert sha256_file(path) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    path.write_bytes(b"abcd")
    assert not source_unchanged(path, snapshot)


def test_disk_estimate_includes_substantial_high_water_reserve() -> None:
    decoded = 5 * 1024**3
    estimate = estimate_disk_required(decoded_bytes=decoded)
    assert estimate > 4 * decoded


def test_resource_plan_is_bounded(tmp_path: Path) -> None:
    plan = build_resource_plan(decoded_bytes=32 * 1024**2, project_path=tmp_path)
    assert 1 <= plan.worker_threads <= 4
    assert 32 * 1024**2 <= plan.compute_chunk_bytes <= 256 * 1024**2
    assert plan.disk_required_bytes > plan.decoded_bytes
