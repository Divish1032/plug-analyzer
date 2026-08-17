"""Versioned, atomic local exports for reviewed analysis results."""

from __future__ import annotations

import csv
import json
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np

from plug_analyzer.models import FinalizedRun
from plug_analyzer.project import ProjectStore


class ExportError(RuntimeError):
    """Raised when a result cannot be safely exported or finalized."""


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _csv_text(headers: Iterable[str], rows: Iterable[Iterable[Any]]) -> str:
    from io import StringIO

    buffer = StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(headers)
    writer.writerows(rows)
    return buffer.getvalue()


def export_analysis_tables(result: Any, destination: Path) -> dict[str, Path]:
    """Write human-readable JSON/CSV tables without silently overwriting files."""

    destination = destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    targets = {
        "summary_json": destination / "analysis-summary.json",
        "per_plane_csv": destination / "per-z-metrics.csv",
        "cross_section_csv": destination / "cross-section-metrics.csv",
    }
    existing = [path for path in targets.values() if path.exists()]
    if existing:
        raise ExportError(f"export destination already contains {existing[0].name}")

    summary = json.dumps(
        result.summary_dict(),
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
    )
    _atomic_text(targets["summary_json"], f"{summary}\n")
    plane = result.per_plane
    _atomic_text(
        targets["per_plane_csv"],
        _csv_text(
            (
                "z_index",
                "area_um2",
                "corrected_integrated_intensity_au",
                "fluorescence_area_integral_au_um2",
                "mean_corrected_intensity_au",
            ),
            (
                (
                    index,
                    plane.area_um2[index],
                    plane.corrected_integrated_intensity_au[index],
                    plane.fluorescence_area_integral_au_um2[index],
                    plane.mean_corrected_intensity_au[index],
                )
                for index in range(plane.area_um2.size)
            ),
        ),
    )
    cross = result.cross_section
    _atomic_text(
        targets["cross_section_csv"],
        _csv_text(
            (
                "position_um",
                "plug_area_um2",
                "lumen_area_um2",
                "occlusion_percent",
                "open_area_um2",
            ),
            zip(
                cross.bin_centers_um,
                cross.plug_area_um2,
                cross.lumen_area_um2,
                cross.occlusion_percent,
                cross.open_area_um2,
                strict=True,
            ),
        ),
    )
    return targets


def _atomic_numpy(path: Path, array: Any) -> None:
    """Write one array to NPY without materializing an array-like source.

    NumPy's documented NPY header writers plus an ``open_memmap`` destination
    let Zarr-backed masks stream one bounded slice at a time. The temporary
    file is atomically published only after every slice is flushed.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        shape = tuple(int(value) for value in array.shape)
        dtype = np.dtype(array.dtype)
        if not shape or any(value < 0 for value in shape):
            raise ExportError("array has an invalid shape")
        destination = np.lib.format.open_memmap(
            temporary,
            mode="w+",
            dtype=dtype,
            shape=shape,
            fortran_order=False,
        )
        try:
            if len(shape) == 1:
                block = max(1, min(shape[0], 8 * 1024**2 // max(1, dtype.itemsize)))
                for start in range(0, shape[0], block):
                    stop = min(shape[0], start + block)
                    destination[start:stop] = array[start:stop]
            else:
                # A single leading-axis plane is bounded for canonical Z/Y/X
                # masks and works for ordinary NumPy arrays too.
                for index in range(shape[0]):
                    destination[index] = array[index]
            destination.flush()
        finally:
            del destination
        # Windows requires a write-capable descriptor for fsync. The temporary
        # file is already complete; reopening read/write only establishes that
        # descriptor before the atomic replace below.
        with temporary.open("r+b") as handle:
            # Ensure the completed temporary is durable before atomic rename.
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def finalize_project_run(
    store: ProjectStore,
    *,
    sample_id: str,
    result: Any,
    run_id: str | None = None,
) -> FinalizedRun:
    """Atomically create immutable run artifacts, then record the SQLite row.

    If SQLite finalization fails, the completed artifact directory remains
    visible for diagnosis; it is never silently deleted.
    """

    identifier = run_id or uuid4().hex
    partial = store.paths.work / f"{identifier}.partial"
    final = store.paths.runs / identifier
    if partial.exists() or final.exists():
        raise ExportError(f"run identifier already exists: {identifier}")
    partial.mkdir(parents=True)
    export_analysis_tables(result, partial)
    _atomic_numpy(partial / "plug-mask.npy", result.plug_mask)
    _atomic_numpy(partial / "threshold-disagreement-mask.npy", result.uncertainty_mask)
    os.replace(partial, final)

    relative_artifacts: Mapping[str, str] = {
        "summary_json": str((final / "analysis-summary.json").relative_to(store.paths.root)),
        "per_plane_csv": str((final / "per-z-metrics.csv").relative_to(store.paths.root)),
        "cross_section_csv": str(
            (final / "cross-section-metrics.csv").relative_to(store.paths.root)
        ),
        "plug_mask": str((final / "plug-mask.npy").relative_to(store.paths.root)),
        "threshold_disagreement_mask": str(
            (final / "threshold-disagreement-mask.npy").relative_to(store.paths.root)
        ),
    }
    finalized = result.to_finalized_run(
        sample_id=sample_id,
        artifacts=relative_artifacts,
        run_id=identifier,
    )
    store.save_finalized_run(finalized)
    return finalized
