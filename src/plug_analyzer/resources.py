from __future__ import annotations

import hashlib
import math
import os
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import psutil

from plug_analyzer.models import ResourcePlan

GIB = 1024**3
MIB = 1024**2
# Reference ``run_analysis`` simultaneously retains the decoded source (native
# dtype), corrected and filtered float64 arrays, several boolean masks, SciPy
# labeling/propagation scratch, and robustness-variant state.  ``22`` is a
# deliberately conservative source-byte amplification for uint16 microscopy
# stacks (44 bytes/voxel); callers with a different dtype should use the
# byte-per-voxel inventory below rather than reinterpret this factor.
REFERENCE_PIPELINE_SOURCE_AMPLIFICATION = 22.0
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


class PreflightError(RuntimeError):
    """Raised when a job cannot safely start."""


@dataclass(frozen=True)
class SourceSnapshot:
    size: int
    modified_ns: int


def safe_project_name(value: str) -> str:
    candidate = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", value.strip())
    candidate = re.sub(r"\s+", " ", candidate).rstrip(". ")
    if not candidate:
        raise ValueError("project name cannot be empty")
    if candidate.upper() in WINDOWS_RESERVED_NAMES:
        candidate = f"{candidate}_project"
    if len(candidate) > 80:
        candidate = candidate[:80].rstrip(". ")
    return candidate


def source_snapshot(path: Path) -> SourceSnapshot:
    stat = path.stat()
    return SourceSnapshot(size=stat.st_size, modified_ns=stat.st_mtime_ns)


def source_unchanged(path: Path, snapshot: SourceSnapshot) -> bool:
    return source_snapshot(path) == snapshot


def sha256_file(
    path: Path,
    *,
    block_bytes: int = 8 * MIB,
    cancelled: Callable[[], bool] | None = None,
) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(block_bytes):
            if cancelled and cancelled():
                raise InterruptedError("fingerprint cancelled")
            digest.update(chunk)
    return digest.hexdigest()


def estimate_disk_required(
    *,
    decoded_bytes: int,
    voxel_count: int | None = None,
    persisted_mask_count: int = 1,
    preview_bytes: int | None = None,
    optional_source_copy_bytes: int = 0,
    stage_scratch_multiplier: float = 2.0,
) -> int:
    """Conservative high-water estimate without assuming compression savings."""
    if decoded_bytes < 0 or persisted_mask_count < 0 or optional_source_copy_bytes < 0:
        raise ValueError("byte counts and mask count must be non-negative")
    if voxel_count is not None and voxel_count < 0:
        raise ValueError("voxel_count must be non-negative")
    preview = preview_bytes if preview_bytes is not None else max(16 * MIB, decoded_bytes // 32)
    persistent = (
        decoded_bytes
        + persisted_mask_count
        * (voxel_count if voxel_count is not None else math.ceil(decoded_bytes / 2))
        + preview
        + optional_source_copy_bytes
    )
    scratch = math.ceil(decoded_bytes * stage_scratch_multiplier)
    atomic_finalize_reserve = decoded_bytes
    high_water = persistent + scratch + atomic_finalize_reserve
    return math.ceil(1.20 * high_water + 2 * GIB)


def build_resource_plan(
    *,
    decoded_bytes: int,
    project_path: Path,
    stage_amplification: float = REFERENCE_PIPELINE_SOURCE_AMPLIFICATION,
    disk_required_bytes: int | None = None,
    require_in_memory_fit: bool = True,
) -> ResourcePlan:
    memory = psutil.virtual_memory()
    physical = int(memory.total)
    available = int(memory.available)
    # ``available`` already reflects pressure from the OS and other processes.
    # Keep a substantial reserve, but cap it at half of currently available RAM
    # so a small verified job is not rejected merely because the machine is busy.
    reserve = min(
        max(512 * MIB, math.ceil(0.10 * physical)),
        math.floor(0.50 * available),
    )
    budget = min(math.floor(0.60 * available), max(0, available - reserve))

    physical_cores = psutil.cpu_count(logical=False) or 1
    cpu_limit = min(4, max(1, physical_cores - 1))
    preferred_chunk = 128 * MIB
    resident_per_thread = 2
    memory_threads = math.floor(
        budget / max(1, resident_per_thread * stage_amplification * preferred_chunk)
    )
    threads = max(1, min(cpu_limit, memory_threads or 1))
    raw_chunk = math.floor(budget / max(1, resident_per_thread * stage_amplification * threads))
    chunk = min(256 * MIB, max(32 * MIB, raw_chunk))
    chunk = max(1 * MIB, (chunk // MIB) * MIB)

    disk = shutil.disk_usage(project_path)
    required = (
        disk_required_bytes
        if disk_required_bytes is not None
        else estimate_disk_required(decoded_bytes=decoded_bytes)
    )
    warnings: list[str] = []
    unsafe_reasons: list[str] = []
    if budget < GIB:
        warnings.append("Less than 1 GiB is safely available for this job.")
    estimated_peak = math.ceil(decoded_bytes * stage_amplification)
    if estimated_peak > budget and require_in_memory_fit:
        reason = (
            "The verified in-memory scientific pipeline would exceed the safe memory budget; "
            "this source needs the future block-equivalent analysis path."
        )
        warnings.append(reason)
        unsafe_reasons.append(reason)
    elif estimated_peak > budget:
        warnings.append(
            "The reference in-memory pipeline exceeds the safe memory budget; "
            "a certified bounded-memory execution path is required."
        )
    if disk.free < required:
        reason = "The project volume does not have enough worst-case free space."
        warnings.append(reason)
        unsafe_reasons.append(reason)
    if available < max(math.ceil(0.10 * physical), math.ceil(1.5 * GIB)):
        warnings.append("System memory is already under the runtime safety reserve.")

    return ResourcePlan(
        decoded_bytes=decoded_bytes,
        available_memory_bytes=available,
        memory_budget_bytes=budget,
        compute_chunk_bytes=chunk,
        worker_threads=threads,
        disk_free_bytes=disk.free,
        disk_required_bytes=required,
        safe_to_start=not unsafe_reasons,
        warnings=tuple(warnings),
    )


def require_safe_plan(plan: ResourcePlan) -> None:
    if not plan.safe_to_start:
        raise PreflightError(" ".join(plan.warnings))


def process_rss() -> int:
    return psutil.Process(os.getpid()).memory_info().rss
