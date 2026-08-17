"""Stable GUI entry point and packaged-dependency smoke probe."""

from __future__ import annotations

import sys
import tempfile
from collections.abc import Sequence
from importlib.metadata import version as distribution_version
from pathlib import Path


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(f"bundle smoke check failed: {message}")


def _exercise_tiff(
    path: Path,
    cache_directory: Path | None = None,
    expected_shape: tuple[int, int, int] | None = None,
) -> None:
    from plug_analyzer.io import (
        VolumeSelection,
        import_to_zarr,
        open_cached_volume,
        open_reader,
        verify_cache,
    )

    reader = open_reader(path)
    info = reader.probe()
    _require(bool(info.scenes), f"no readable scene in {path}")
    shape = reader.selected_shape(VolumeSelection())
    _require(all(size > 0 for size in shape), f"invalid selected shape {shape}")
    if expected_shape is not None:
        _require(shape == expected_shape, f"TIFF shape {shape} does not match {expected_shape}")
    plane = reader.read_plane(
        VolumeSelection(),
        0,
        slice(0, min(shape[1], 8)),
        slice(0, min(shape[2], 8)),
    )
    _require(plane.ndim == 2 and plane.size > 0, "TIFF plane read returned no pixels")
    if cache_directory is not None:
        chunks = tuple(
            max(1, min(size, limit)) for size, limit in zip(shape, (2, 10, 10), strict=True)
        )
        manifest = import_to_zarr(
            reader,
            VolumeSelection(),
            cache_directory,
            chunk_shape=chunks,
        )
        _require(manifest.status == "complete", "TIFF-to-Zarr cache did not complete")
        cached = open_cached_volume(cache_directory)
        _require(tuple(cached.shape) == shape, "cached TIFF shape does not match the source")
        _require(verify_cache(cache_directory).valid, "TIFF-to-Zarr cache verification failed")


def _bundle_smoke(regression_tiff: Path | None) -> int:
    """Exercise imports and work paths that frozen-app analysis depends on."""

    import dask.array as da
    import imagecodecs
    import nd2
    import numpy as np
    import pyqtgraph
    import scipy.ndimage as ndi
    import scipy.stats as stats
    import tifffile
    import zarr
    from PySide6 import QtOpenGL, QtOpenGLWidgets, QtSvg
    from PySide6.QtWidgets import QApplication
    from scipy._external.array_api_compat.numpy import fft as array_api_fft
    from scipy._external.array_api_compat.numpy import linalg as array_api_linalg
    from skimage.registration import phase_cross_correlation

    from plug_analyzer import app as analyzer_app
    from plug_analyzer import controller, large_pipeline, service
    from plug_analyzer.pipeline import (
        PipelineConfig,
        RectangularRoi,
        RobustnessMode,
        masks_from_rectangles,
        run_analysis,
    )
    from plug_analyzer.ui import MainWindow

    _require(bool(imagecodecs.version()), "imagecodecs did not report a version")
    _require(
        distribution_version("numpy") == np.__version__,
        "bundled NumPy distribution metadata does not match the runtime",
    )
    _require(hasattr(nd2, "ND2File"), "nd2 reader API is unavailable")
    _require(bool(pyqtgraph.__version__), "pyqtgraph did not report a version")
    _require(all((QtOpenGL, QtOpenGLWidgets, QtSvg)), "required Qt modules are unavailable")
    _require(hasattr(analyzer_app, "main"), "application entry point is unavailable")
    _require(hasattr(controller, "ApplicationController"), "GUI controller is unavailable")
    _require(hasattr(large_pipeline, "run_large_analysis"), "large pipeline is unavailable")
    _require(hasattr(service, "preflight_source"), "analysis service is unavailable")

    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.close()
    application.processEvents()

    image = np.full((3, 20, 20), 10, dtype=np.uint16)
    image[:, :, 0:2] = 9
    image[:, :, 3:5] = 11
    image[:, 5:8, 10:14] = 100

    filtered = ndi.gaussian_filter(image.astype(np.float64), sigma=(0.0, 0.5, 0.5))
    _require(filtered.shape == image.shape, "SciPy filtering changed the array shape")
    _require(
        bool(np.all(np.isfinite(stats.median_abs_deviation(filtered)))),
        "SciPy MAD is not finite",
    )
    rank_correlation = stats.spearmanr((1.0, 2.0, 3.0), (1.0, 2.0, 3.0)).statistic
    _require(float(rank_correlation) == 1.0, "SciPy rank correlation is unavailable")
    transformed = array_api_fft.fft(np.ones(4, dtype=np.float64))
    _require(transformed.shape == (4,), "vendored Array API FFT is unavailable")
    norm = array_api_linalg.vector_norm(np.array([3.0, 4.0]))
    _require(float(norm) == 5.0, "vendored Array API linear algebra is unavailable")

    reference = np.zeros((8, 8), dtype=np.float64)
    reference[2, 3] = 1.0
    shift, _, _ = phase_cross_correlation(reference, np.roll(reference, 1, axis=0))
    _require(np.allclose(shift, (-1.0, 0.0)), "scikit-image registration is unavailable")

    lazy = da.from_array(image, chunks=(1, 10, 10))
    lazy_sum = lazy.sum().compute(scheduler="synchronous")
    _require(int(lazy_sum) == int(image.sum()), "Dask computation disagrees with NumPy")

    masks = masks_from_rectangles(
        image.shape,
        background_rois=(RectangularRoi(0, 20, 0, 5),),
        analysis_roi=RectangularRoi(0, 20, 5, 20),
        lumen_roi=RectangularRoi(0, 20, 5, 20),
        envelope_roi=RectangularRoi(5, 8, 10, 14),
    )
    result = run_analysis(
        image,
        masks=masks,
        config=PipelineConfig(
            spacing_zyx_um=(2.0, 1.0, 1.0),
            filter_sigma_um=0.0,
            low_noise_multiplier=2.0,
            high_noise_multiplier=4.0,
            minimum_component_volume_um3=1.0,
            min_reference_pixels_per_plane=20,
            saturation_threshold=255.0,
            robustness_mode=RobustnessMode.STANDARD,
        ),
    )
    _require(result.plug_mask.shape == image.shape, "analysis pipeline returned the wrong shape")
    _require(result.volume.observed_volume_um3 > 0, "analysis pipeline found no plug volume")

    with tempfile.TemporaryDirectory(prefix="plug-analyzer-bundle-smoke-") as temporary:
        temporary_path = Path(temporary)
        zarr_path = temporary_path / "smoke.zarr"
        array = zarr.open_array(
            zarr_path,
            mode="w",
            shape=image.shape,
            chunks=(1, 10, 10),
            dtype=image.dtype,
        )
        array[:] = image
        reopened = zarr.open_array(zarr_path, mode="r")
        _require(np.array_equal(reopened[:], image), "Zarr round trip changed pixels")

        synthetic_tiff = temporary_path / "smoke.tif"
        tiff_image = np.concatenate((image, image[:1]), axis=0)
        tifffile.imwrite(
            synthetic_tiff,
            tiff_image,
            imagej=True,
            compression="zlib",
            photometric="minisblack",
            metadata={"axes": "ZYX", "spacing": 2.0, "unit": "um"},
        )
        _require(not nd2.is_supported_file(synthetic_tiff), "ND2 detector accepted a TIFF")
        _exercise_tiff(
            synthetic_tiff,
            temporary_path / "cache",
            expected_shape=tiff_image.shape,
        )

    if regression_tiff is not None:
        resolved = regression_tiff.expanduser().resolve()
        _require(resolved.is_file(), f"regression TIFF does not exist: {resolved}")
        _exercise_tiff(resolved)

    print("bundle smoke: ok", flush=True)
    return 0


def _entry(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "--bundle-smoke":
        if len(arguments) > 2:
            print("usage: PlugAnalyzer --bundle-smoke [TIFF]", file=sys.stderr)
            return 2
        regression_tiff = Path(arguments[1]) if len(arguments) == 2 else None
        return _bundle_smoke(regression_tiff)

    from plug_analyzer.app import main

    return main()


if __name__ == "__main__":
    raise SystemExit(_entry())
