from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import tifffile

from plug_analyzer.io import ImportCancelled, VolumeSelection
from plug_analyzer.service import prepare_source_cache


def test_retry_reuses_cache_published_before_verification_cancellation(tmp_path: Path) -> None:
    source = tmp_path / "source.tif"
    volume = np.arange(4 * 20 * 30, dtype=np.uint16).reshape(4, 20, 30)
    tifffile.imwrite(
        source,
        volume,
        imagej=True,
        metadata={"axes": "ZYX", "spacing": 1.0, "unit": "um"},
        resolution=(1, 1),
    )
    project = tmp_path / "project"
    project.mkdir()
    verification_started = False

    def progress(stage: str, _fraction: float, _detail: str) -> None:
        nonlocal verification_started
        if stage == "verify":
            verification_started = True

    with pytest.raises(ImportCancelled):
        prepare_source_cache(
            project,
            source_path=source,
            selection=VolumeSelection(),
            sample_id="stable-id",
            progress=progress,
            cancelled=lambda: verification_started,
        )

    published_cache = project / "data" / "stable-id"
    assert published_cache.is_dir()
    resumed = prepare_source_cache(
        project,
        source_path=source,
        selection=VolumeSelection(),
        sample_id="stable-id",
    )
    assert resumed.sample_id == "stable-id"
    assert resumed.cache_relative_path == "data/stable-id"
    assert resumed.cache_verification_errors == ()
