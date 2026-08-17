"""Headless command-line entry point for inspection and small-stack analysis.

The desktop application is the primary user interface.  This module provides a
small, deterministic vertical slice for automation, troubleshooting, and
reproducible SME checks without requiring Qt to display a window.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from plug_analyzer import __version__
from plug_analyzer.exports import ExportError, export_analysis_tables
from plug_analyzer.io import (
    MicroscopeIOError,
    VolumeSelection,
    open_reader,
)
from plug_analyzer.io.models import AxisCalibration, DatasetInfo, model_to_dict
from plug_analyzer.models import ResourcePlan
from plug_analyzer.pipeline import (
    PipelineConfig,
    RectangularRoi,
    RobustnessMode,
    masks_from_rectangles,
    run_analysis,
)
from plug_analyzer.resources import (
    REFERENCE_PIPELINE_SOURCE_AMPLIFICATION,
    PreflightError,
    require_safe_plan,
)
from plug_analyzer.service import preflight_source

EXIT_INPUT = 2
EXIT_UNSAFE = 3
EXIT_ANALYSIS = 4

# The present candidate pipeline creates several full-size floating-point and
# boolean arrays. Import is out-of-core elsewhere in the application, but this
# one-shot command must fail before decoding a stack that cannot safely fit.
IN_MEMORY_STAGE_AMPLIFICATION = REFERENCE_PIPELINE_SOURCE_AMPLIFICATION


class CliInputError(ValueError):
    """A user-correctable command-line input problem."""


class UnsafeAnalysisError(PreflightError):
    """The selected stack cannot safely use the current in-memory pipeline."""


def _positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected a number, got {value!r}") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive finite number")
    return parsed


def _non_negative_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected a number, got {value!r}") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("value must be a non-negative finite number")
    return parsed


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected an integer, got {value!r}") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def _rectangle(value: str) -> RectangularRoi:
    """Parse half-open ``Y_START:Y_STOP,X_START:X_STOP`` coordinates."""

    normalized = value.replace(",", ":")
    parts = normalized.split(":")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(
            "ROI must be Y_START:Y_STOP,X_START:X_STOP (half-open coordinates)"
        )
    try:
        y_start, y_stop, x_start, x_stop = (int(part.strip()) for part in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("ROI coordinates must be integers") from exc
    if min(y_start, y_stop, x_start, x_stop) < 0:
        raise argparse.ArgumentTypeError("ROI coordinates cannot be negative")
    if y_start >= y_stop or x_start >= x_stop:
        raise argparse.ArgumentTypeError("ROI stop coordinates must exceed start coordinates")
    return RectangularRoi(y_start, y_stop, x_start, x_stop)


def _existing_storage_path(requested: Path) -> Path:
    """Find the existing ancestor whose free space will hold the requested path."""

    candidate = requested.expanduser().resolve()
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    if not candidate.exists():  # Defensive for unusual virtual filesystems.
        raise CliInputError(f"No existing storage ancestor for: {requested}")
    if candidate.is_file():
        candidate = candidate.parent
    return candidate


def _selection(args: argparse.Namespace) -> VolumeSelection:
    return VolumeSelection(
        scene=args.scene,
        time=args.time,
        channel=args.channel,
        z_start=args.z_start,
        z_stop=args.z_stop,
    )


def _axis_payload(axis: AxisCalibration) -> dict[str, Any]:
    return {
        "value_um": axis.value_um,
        "source": axis.source.value,
        "raw_value": axis.raw_value,
        "raw_unit": axis.raw_unit,
        "alternatives": [model_to_dict(candidate) for candidate in axis.alternatives],
    }


def _resource_payload(plan: ResourcePlan) -> dict[str, Any]:
    payload = plan.model_dump(mode="json")
    payload["one_shot_estimated_peak_bytes"] = plan.decoded_bytes * IN_MEMORY_STAGE_AMPLIFICATION
    payload["one_shot_memory_safe"] = (
        payload["one_shot_estimated_peak_bytes"] <= plan.memory_budget_bytes
    )
    return payload


def _inspection_payload(
    info: DatasetInfo,
    *,
    selection: VolumeSelection,
    plan: ResourcePlan,
    storage_path: Path,
) -> dict[str, Any]:
    scene = info.scenes[selection.scene]
    selected_z_stop = selection.z_stop if selection.z_stop is not None else scene.zyx_shape[0]
    return {
        "schema_version": 1,
        "app_version": __version__,
        "source": {
            "path": str(info.path),
            "size_bytes": info.path.stat().st_size,
            "reader": info.reader_id,
            "format": info.source_format.value,
        },
        "selection": {
            **model_to_dict(selection),
            "z_stop": selected_z_stop,
            "shape_zyx": [selected_z_stop - selection.z_start, *scene.zyx_shape[1:]],
        },
        "selected_scene": model_to_dict(scene),
        "scenes": [model_to_dict(item) for item in info.scenes],
        "calibration": {
            "x": _axis_payload(info.calibration.x),
            "y": _axis_payload(info.calibration.y),
            "z": _axis_payload(info.calibration.z),
            "complete_xyz": info.calibration.complete_xyz,
        },
        "warnings": list(info.warnings),
        "resource_volume_path": str(storage_path),
        "resource_plan": _resource_payload(plan),
    }


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False))


def _effective_spacing(
    info: DatasetInfo,
    *,
    x_override: float | None,
    y_override: float | None,
    z_override: float | None,
) -> tuple[tuple[float, float, float], dict[str, dict[str, Any]]]:
    overrides = {"x": x_override, "y": y_override, "z": z_override}
    selected: dict[str, float] = {}
    audit: dict[str, dict[str, Any]] = {}
    for name in ("x", "y", "z"):
        metadata_axis = getattr(info.calibration, name)
        override = overrides[name]
        value = override if override is not None else metadata_axis.value_um
        if value is None:
            raise CliInputError(
                f"{name.upper()} calibration is missing. Supply --{name}-um with the "
                "SME-confirmed sampling in micrometres."
            )
        if not math.isfinite(value) or value <= 0:
            raise CliInputError(f"{name.upper()} calibration must be positive and finite.")
        selected[name] = float(value)
        audit[name] = {
            "value_um": float(value),
            "source": "manual-cli" if override is not None else metadata_axis.source.value,
            "overrode_metadata": override is not None,
            "metadata_value_um": metadata_axis.value_um,
        }
    # Scientific functions consume spacing in canonical Z/Y/X order.
    return (selected["z"], selected["y"], selected["x"]), audit


def _assert_one_shot_safe(plan: ResourcePlan) -> None:
    require_safe_plan(plan)
    estimated_peak = plan.decoded_bytes * IN_MEMORY_STAGE_AMPLIFICATION
    if estimated_peak > plan.memory_budget_bytes:
        raise UnsafeAnalysisError(
            "Selected stack is too large for the current one-shot in-memory analysis: "
            f"estimated peak {estimated_peak:,} bytes exceeds the safe budget "
            f"{plan.memory_budget_bytes:,} bytes. Select a smaller Z range or use the "
            "desktop import workflow; the CLI will not decode this stack."
        )


def _preflight(
    source: Path,
    *,
    storage_target: Path,
    selection: VolumeSelection,
) -> tuple[DatasetInfo, ResourcePlan, Path]:
    storage_path = _existing_storage_path(storage_target)
    info, plan = preflight_source(
        source.expanduser().resolve(),
        project_path=storage_path,
        selection=selection,
    )
    return info, plan, storage_path


def _inspect(args: argparse.Namespace) -> int:
    source = Path(args.source)
    selection = _selection(args)
    requested_storage = Path(args.project_path) if args.project_path else source.parent
    info, plan, storage_path = _preflight(
        source,
        storage_target=requested_storage,
        selection=selection,
    )
    _print_json(
        _inspection_payload(
            info,
            selection=selection,
            plan=plan,
            storage_path=storage_path,
        )
    )
    return 0


def _analysis_progress(stage: str, fraction: float, message: str) -> None:
    print(f"[{100 * fraction:5.1f}%] {stage}: {message}", file=sys.stderr)


def _analyze(args: argparse.Namespace) -> int:
    source = Path(args.source).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    selection = _selection(args)
    info, plan, _ = _preflight(source, storage_target=output, selection=selection)
    _assert_one_shot_safe(plan)

    spacing_zyx, calibration_audit = _effective_spacing(
        info,
        x_override=args.x_um,
        y_override=args.y_um,
        z_override=args.z_um,
    )
    reader = open_reader(source)
    shape = reader.selected_shape(selection)
    background_rois = tuple(args.background_roi)
    masks = masks_from_rectangles(
        shape,
        background_rois=background_rois,
        analysis_roi=args.analysis_roi,
        lumen_roi=args.lumen_roi,
        envelope_roi=args.envelope_roi,
    )

    print("Reading the preflight-approved selected volume...", file=sys.stderr)
    volume = reader.read_region(
        selection,
        (slice(None), slice(None), slice(None)),
    )
    significant_bits = info.scenes[selection.scene].significant_bits
    saturation_threshold = (
        args.saturation_threshold
        if args.saturation_threshold is not None
        else float((1 << significant_bits) - 1)
    )
    config = PipelineConfig(
        spacing_zyx_um=spacing_zyx,
        filter_sigma_um=args.filter_sigma_um,
        low_noise_multiplier=args.low_noise_multiplier,
        high_noise_multiplier=args.high_noise_multiplier,
        minimum_component_volume_um3=args.minimum_component_volume_um3,
        min_reference_pixels_per_plane=args.min_reference_pixels,
        saturation_threshold=saturation_threshold,
        robustness_mode=RobustnessMode(args.robustness),
    )
    result = run_analysis(
        np.asarray(volume),
        masks=masks,
        config=config,
        progress=_analysis_progress,
    )
    paths = export_analysis_tables(result, output)
    _print_json(
        {
            "status": "candidate-analysis-complete",
            "source": str(source),
            "selection": model_to_dict(selection),
            "shape_zyx": list(shape),
            "calibration": calibration_audit,
            "geometry_source": masks.geometry_source,
            "outputs": {name: str(path) for name, path in paths.items()},
            "warnings": list(result.warnings),
        }
    )
    return 0


def _add_selection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--scene", type=int, default=0, help="zero-based scene/position index")
    parser.add_argument("--time", type=int, default=0, help="zero-based time-point index")
    parser.add_argument("--channel", type=int, default=0, help="zero-based channel index")
    parser.add_argument("--z-start", type=int, default=0, help="first Z plane (inclusive)")
    parser.add_argument("--z-stop", type=int, help="last Z plane (exclusive)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plug-analyzer",
        description="Inspect or run candidate analysis on a microscope Z-stack.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    inspect_parser = commands.add_parser(
        "inspect",
        help="probe metadata and resource needs without decoding the complete stack",
    )
    inspect_parser.add_argument("source", help="TIFF/OME-TIFF/ImageJ TIFF/BigTIFF/ND2 source")
    inspect_parser.add_argument(
        "--project-path",
        "--project",
        help="planned project/output location used for the free-space estimate",
    )
    _add_selection_arguments(inspect_parser)
    inspect_parser.set_defaults(handler=_inspect)

    analyze_parser = commands.add_parser(
        "analyze",
        help="run the deterministic candidate pipeline on a preflight-approved small stack",
    )
    analyze_parser.add_argument("source", help="TIFF/OME-TIFF/ImageJ TIFF/BigTIFF/ND2 source")
    analyze_parser.add_argument("--output", required=True, help="new or empty output directory")
    _add_selection_arguments(analyze_parser)
    analyze_parser.add_argument(
        "--x-um",
        type=_positive_float,
        help="SME-confirmed X sampling override in micrometres",
    )
    analyze_parser.add_argument(
        "--y-um",
        type=_positive_float,
        help="SME-confirmed Y sampling override in micrometres",
    )
    analyze_parser.add_argument(
        "--z-um",
        type=_positive_float,
        help="SME-confirmed Z step override in micrometres",
    )
    analyze_parser.add_argument(
        "--background-roi",
        action="append",
        required=True,
        type=_rectangle,
        metavar="Y0:Y1,X0:X1",
        help="reviewed plug-free rectangle; repeat for multiple bands",
    )
    analyze_parser.add_argument(
        "--analysis-roi",
        type=_rectangle,
        metavar="Y0:Y1,X0:X1",
        help="reviewed analysis rectangle (default: full image)",
    )
    analyze_parser.add_argument(
        "--lumen-roi",
        type=_rectangle,
        metavar="Y0:Y1,X0:X1",
        help="reviewed lumen rectangle (default: analysis rectangle/full image)",
    )
    analyze_parser.add_argument(
        "--envelope-roi",
        type=_rectangle,
        metavar="Y0:Y1,X0:X1",
        help="reviewed plug envelope needed for apparent low-fluorescence fraction",
    )
    analyze_parser.add_argument(
        "--filter-sigma-um",
        type=_non_negative_float,
        default=0.75,
        help="physical Gaussian sigma (default: 0.75)",
    )
    analyze_parser.add_argument(
        "--low-noise-multiplier",
        type=_non_negative_float,
        default=2.0,
        help="low hysteresis threshold multiplier (default: 2)",
    )
    analyze_parser.add_argument(
        "--high-noise-multiplier",
        type=_non_negative_float,
        default=4.0,
        help="high hysteresis threshold multiplier (default: 4)",
    )
    analyze_parser.add_argument(
        "--minimum-component-volume-um3",
        type=_non_negative_float,
        default=5.0,
        help="remove smaller connected components (default: 5)",
    )
    analyze_parser.add_argument(
        "--min-reference-pixels",
        type=_positive_int,
        default=1_000,
        help="minimum background pixels per plane (default: 1000)",
    )
    analyze_parser.add_argument(
        "--saturation-threshold",
        type=_non_negative_float,
        help="detector saturation value (default: maximum from significant bits)",
    )
    analyze_parser.add_argument(
        "--robustness",
        choices=tuple(item.value for item in RobustnessMode),
        default=RobustnessMode.STANDARD.value,
        help="predeclared threshold-variation check (default: standard)",
    )
    analyze_parser.set_defaults(handler=_analyze)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI, returning a process exit status for programmatic tests."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except UnsafeAnalysisError as exc:
        print(f"error: unsafe resource plan: {exc}", file=sys.stderr)
        return EXIT_UNSAFE
    except PreflightError as exc:
        print(f"error: unsafe resource plan: {exc}", file=sys.stderr)
        return EXIT_UNSAFE
    except (CliInputError, MicroscopeIOError, ExportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INPUT
    except (MemoryError, OSError, ValueError) as exc:
        print(f"error: analysis failed: {exc}", file=sys.stderr)
        return EXIT_ANALYSIS


if __name__ == "__main__":
    raise SystemExit(main())
