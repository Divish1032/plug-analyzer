from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import tifffile

from plug_analyzer import __version__, cli
from plug_analyzer.io import probe_source
from plug_analyzer.models import ResourcePlan


def _calibrated_stack(path: Path) -> np.ndarray:
    image = np.full((3, 12, 20), 10, dtype=np.uint16)
    image[:, :, 0:2] = 9
    image[:, :, 3:5] = 11
    image[:, 4:8, 10:15] = 100
    tifffile.imwrite(
        path,
        image,
        imagej=True,
        metadata={"axes": "ZYX", "spacing": 2.0, "unit": "um"},
        resolution=(2, 4),
    )
    return image


def _relax_host_plan_for_small_test(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the real probe while making tests independent of host memory pressure."""

    real_preflight = cli.preflight_source

    def test_preflight(*args, **kwargs):
        info, plan = real_preflight(*args, **kwargs)
        minimum_budget = max(
            plan.memory_budget_bytes,
            plan.decoded_bytes * cli.IN_MEMORY_STAGE_AMPLIFICATION,
        )
        return info, plan.model_copy(
            update={
                "memory_budget_bytes": minimum_budget,
                "safe_to_start": True,
                "warnings": (),
            }
        )

    monkeypatch.setattr(cli, "preflight_source", test_preflight)


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(["--version"])

    assert caught.value.code == 0
    assert capsys.readouterr().out.strip() == f"plug-analyzer {__version__}"


def test_inspect_emits_concise_json_without_decoding_pixels(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "calibrated.tif"
    _calibrated_stack(source)

    status = cli.main(["inspect", str(source), "--project-path", str(tmp_path / "future")])

    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["source"]["format"] == "imagej-tiff"
    assert payload["selection"]["shape_zyx"] == [3, 12, 20]
    assert payload["calibration"]["complete_xyz"]
    assert payload["calibration"]["x"]["value_um"] == pytest.approx(0.5)
    assert payload["calibration"]["y"]["value_um"] == pytest.approx(0.25)
    assert payload["calibration"]["z"]["value_um"] == pytest.approx(2.0)
    assert payload["resource_plan"]["decoded_bytes"] == 3 * 12 * 20 * 2
    assert "raw_metadata" not in payload


def test_analyze_runs_candidate_pipeline_and_exports_tables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "calibrated.tif"
    _calibrated_stack(source)
    output = tmp_path / "candidate-output"
    _relax_host_plan_for_small_test(monkeypatch)

    status = cli.main(
        [
            "analyze",
            str(source),
            "--output",
            str(output),
            "--background-roi",
            "0:12,0:5",
            "--analysis-roi",
            "0:12,5:20",
            "--lumen-roi",
            "0:12,5:20",
            "--envelope-roi",
            "4:8,10:15",
            "--filter-sigma-um",
            "0",
            "--minimum-component-volume-um3",
            "0.1",
            "--min-reference-pixels",
            "10",
            "--saturation-threshold",
            "255",
            "--robustness",
            "off",
        ]
    )

    captured = capsys.readouterr()
    assert status == 0, captured.err
    completion = json.loads(captured.out)
    assert completion["status"] == "candidate-analysis-complete"
    assert completion["calibration"]["z"]["source"] == "imagej-metadata"
    assert "Reading the preflight-approved" in captured.err
    summary = json.loads((output / "analysis-summary.json").read_text(encoding="utf-8"))
    assert summary["metrics"]["maximum_plane_area_um2"] == pytest.approx(2.5)
    assert summary["metrics"]["observed_volume_um3"] == pytest.approx(15.0)
    assert (output / "per-z-metrics.csv").is_file()
    assert (output / "cross-section-metrics.csv").is_file()


def test_manual_calibration_overrides_missing_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "plain.tif"
    image = np.full((2, 8, 12), 10, dtype=np.uint16)
    image[:, :, :2] = 9
    image[:, :, 2:4] = 11
    image[:, 3:6, 6:9] = 50
    tifffile.imwrite(source, image, photometric="minisblack")
    _relax_host_plan_for_small_test(monkeypatch)

    missing_status = cli.main(
        [
            "analyze",
            str(source),
            "--output",
            str(tmp_path / "missing"),
            "--background-roi",
            "0:8,0:4",
            "--x-um",
            "1",
            "--y-um",
            "1",
        ]
    )
    missing_error = capsys.readouterr().err
    assert missing_status == cli.EXIT_INPUT
    assert "Z calibration is missing" in missing_error
    assert "--z-um" in missing_error

    override_status = cli.main(
        [
            "analyze",
            str(source),
            "--output",
            str(tmp_path / "manual"),
            "--background-roi",
            "0:8,0:4",
            "--analysis-roi",
            "0:8,4:12",
            "--x-um",
            "1",
            "--y-um",
            "1",
            "--z-um",
            "1.5",
            "--filter-sigma-um",
            "0",
            "--minimum-component-volume-um3",
            "0",
            "--min-reference-pixels",
            "8",
            "--robustness",
            "off",
        ]
    )
    completion = json.loads(capsys.readouterr().out)
    assert override_status == 0
    assert completion["calibration"]["z"] == {
        "metadata_value_um": None,
        "overrode_metadata": True,
        "source": "manual-cli",
        "value_um": 1.5,
    }


def test_unsafe_one_shot_plan_refuses_before_pixel_decode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "stack.tif"
    _calibrated_stack(source)
    info = probe_source(source)
    plan = ResourcePlan(
        decoded_bytes=100,
        available_memory_bytes=1_000,
        memory_budget_bytes=799,
        compute_chunk_bytes=100,
        worker_threads=1,
        disk_free_bytes=10_000,
        disk_required_bytes=1_000,
        safe_to_start=True,
    )
    monkeypatch.setattr(cli, "preflight_source", lambda *args, **kwargs: (info, plan))

    def pixel_decode_would_be_a_bug(*args, **kwargs):
        raise AssertionError("reader opened after unsafe preflight")

    monkeypatch.setattr(cli, "open_reader", pixel_decode_would_be_a_bug)
    status = cli.main(
        [
            "analyze",
            str(source),
            "--output",
            str(tmp_path / "output"),
            "--background-roi",
            "0:12,0:5",
        ]
    )

    captured = capsys.readouterr()
    assert status == cli.EXIT_UNSAFE
    assert "will not decode this stack" in captured.err
    assert not (tmp_path / "output").exists()


def test_unsupported_source_returns_clear_nonzero_status(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "not-an-image.bin"
    source.write_bytes(b"plain text")

    status = cli.main(["inspect", str(source)])

    captured = capsys.readouterr()
    assert status == cli.EXIT_INPUT
    assert "not a recognized TIFF" in captured.err


@pytest.mark.integration
def test_supplied_stack_inspect_smoke(capsys: pytest.CaptureFixture[str]) -> None:
    source = Path(__file__).resolve().parents[2] / "test.tif"
    if not source.is_file():
        pytest.skip("supplied microscope regression stack is not present")

    assert cli.main(["inspect", str(source)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["selection"]["shape_zyx"] == [62, 234, 1024]
    assert payload["selected_scene"]["significant_bits"] == 12
    assert payload["calibration"]["z"]["value_um"] == pytest.approx(0.446)
    assert payload["resource_plan"]["decoded_bytes"] == 62 * 234 * 1024 * 2
    assert payload["resource_plan"]["one_shot_estimated_peak_bytes"] == (
        cli.IN_MEMORY_STAGE_AMPLIFICATION * 62 * 234 * 1024 * 2
    )
