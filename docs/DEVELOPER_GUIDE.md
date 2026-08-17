# Developer Guide

## Runtime and setup

The project uses Python 3.12, PySide6/Qt Widgets, PyQtGraph, NumPy/SciPy/scikit-image, tifffile/nd2, Zarr, Pydantic, and SQLite. `uv.lock` is the reproducible dependency source.

```bash
cd /Users/itachi/Documents/Github/experiments/experiment1/plug-analyzer-prototype
uv sync --frozen --extra dev --extra packaging
uv run plug-analyzer-gui
```

Do not modify or regenerate `../test.tif`. Tests that normalize it use temporary directories.

## Architecture

```text
PySide6 UI
    |
controller.py          state, background jobs, cancel, project switching
    |
service.py             import/cache/analysis/save orchestration
    |----------------------------------------------|
io/              analysis/pipeline/large_pipeline   project/validation/exports
TIFF/ND2         deterministic bounded analysis     SQLite + visible artifacts
    |
lossless Zarr cache
```

Important boundaries:

- Readers normalize one selected series to canonical `Z, Y, X` without silently flattening extra dimensions.
- Source import streams to a checksummed Zarr cache and is resumable. Database publication occurs only after verification.
- The controller runs import and analysis through Qt's worker pool, checks project/source generation tokens, and cooperatively cancels at safe boundaries.
- `service.analyze_cached_volume` chooses `pipeline.run_analysis` only when its conservative source-byte amplification fits the safe budget. Otherwise the controller supplies a project-local workspace to `large_pipeline.run_large_analysis`.
- The disk-backed engine uses virtual rectangular or polygon-prism masks, chunk halos, disk-backed intermediate arrays, and global component reconciliation. It includes exact disk-backed open-path connectivity and EDT/connectivity-search bottleneck clearance.
- Large result masks are streamed plane-by-plane into the immutable NPY artifact during save instead of being materialized in RAM.
- The dormant pre-contact correction implementation is a lazy exact-grid registered difference volume; raw post-contact data remains available for saturation QC. It is not exposed in the current SME workflow; see [Prototype scope](PROTOTYPE_SCOPE.md).
- Comparisons pass through metric-aware compatibility rules. Spatial validation refuses any mask that does not exactly match the saved run's ZYX grid.
- Finalized runs are immutable SQLite records plus visible versioned artifacts. Saved-run table exports refuse an occupied artifact target; GUI exports write atomically to the path chosen by the user.

## Source support

| Source | Implementation status |
|---|---|
| TIFF / multipage TIFF | Implemented and tested |
| ImageJ TIFF | Implemented; supplied stack accepted |
| OME-TIFF | Implemented with physical metadata tests |
| BigTIFF | Implemented with synthetic tests |
| Nikon ND2 | Adapter and mocked multidimensional tests implemented; genuine lab file acceptance pending |
| Internal Zarr | Lossless project cache, not a user input format |

An ambiguous axis layout or unsupported source fails closed. Add formats through the reader adapter; do not add a universal conversion layer without genuine files and packaging evidence.

## Verification

Run formatting/lint and the full suite from the project root:

```bash
UV_CACHE_DIR=.uv-cache uv run ruff format --check src tests scripts
UV_CACHE_DIR=.uv-cache uv run ruff check src tests scripts
QT_QPA_PLATFORM=offscreen UV_CACHE_DIR=.uv-cache uv run pytest -q
```

Latest local development gate on 14 August 2026: Ruff format/lint clean and `135 passed`. This is repository verification on the development Mac, not a clean-machine installer test. The UI regression suite also initializes Qt with a deliberately dark system palette and verifies that application startup restores the complete light-only palette.

Useful focused checks:

```bash
UV_CACHE_DIR=.uv-cache uv run pytest -q tests/test_io_real_tiff.py tests/test_pipeline.py
QT_QPA_PLATFORM=offscreen UV_CACHE_DIR=.uv-cache uv run pytest -q \
  tests/test_ui_workflow.py tests/test_controller_workflow.py
UV_CACHE_DIR=.uv-cache uv run pytest -q \
  tests/test_large_pipeline_equivalence.py tests/test_service_large_integration.py
```

The real-TIFF regression verifies metadata, representative planes, cache equality, and a segmentation fingerprint. It is deliberately labelled software regression, not scientific ground truth.

Inspect the fixture manually through the CLI:

```bash
UV_CACHE_DIR=.uv-cache uv run plug-analyzer inspect ../test.tif
```

## Desktop development flow

1. Create/open a visible project.
2. Inspect a source and review its resource plan.
3. Confirm calibration; review rectangle or editable polygon-prism ROIs in linked XY/XZ/YZ views.
4. Run; first use builds/verifies the cache, then executes the scientific path.
5. Review overlay/QC, explicitly save, export, and compare.

When changing a metric, update together:

- its formula/tests in `analysis/` or `pipeline.py`;
- scalar, per-plane, or cross-section serialization;
- finalized `MetricValue` availability and qualification;
- UI display/comparison behavior;
- method and limitation documentation.

Never convert a missing/unsafe measurement to zero. Use an explicit unavailable, warning, imaged-volume-only, or lower-bound state.

## Project format

`ProjectStore` schema version is currently 2, with an in-place migration from writable schema-1 projects. Project paths stored in saved runs must remain relative to the project root. The original source is referenced by absolute path plus SHA-256; the cache is a project-relative rebuildable copy. Disk-backed analysis workspaces are created under `work/` and are included in the visible storage total.

One live writer owns `.plug-analyzer.lock`. A second instance may open read-only. A stale same-host lock is removed only when its process no longer exists.

Do not delete cache data unless the resolved target is directly beneath the project's `data/` folder and the original source checksum matches. Keep incomplete/diagnostic artifacts visible instead of silently erasing evidence.

## Native packaging

Build on each target OS; do not cross-build Windows from macOS.

The recommended commands are deliberately separate:

```bash
make setup
make check
make build     # creates a fresh installer for the current native OS
make deploy    # verifies and installs that existing installer; never builds
```

Use `make build-mac` / `make deploy-mac` or `make build-windows` /
`make deploy-windows` when an explicit target is clearer. `make verify` checks the current native
release without installing it, and `make artifact` prints the installer path. These targets read
the version already present in `pyproject.toml`; they never rewrite or increment it.

Apple Silicon macOS:

```bash
./scripts/build_macos_arm64.sh --clean \
  --protocol-version candidate-v1-unlocked
```

Windows x64 PowerShell:

```powershell
.\scripts\build_windows_x64.ps1 -Clean `
  -ProtocolVersion candidate-v1-unlocked
```

Outputs go below `dist/release/<version>/<platform>/` with build information, third-party notices, smoke checklist, manifest, and SHA-256 file. Run the native clean-machine checklist before handoff. The current pilot is unsigned; do not instruct users to disable Gatekeeper or SmartScreen.

See [Packaging and internal release](../packaging/README.md) for the exact artifact contract.

## Scientific release gate

Do not rename the protocol from `candidate-v1-unlocked` or present results as validated until:

- the SME freezes geometry and parameters on a declared development set;
- held-out comparisons meet predeclared tolerances;
- acquisition compatibility is recorded;
- genuine ND2 and large-file inputs pass acceptance where they are in scope;
- clean-machine installers pass on both target operating systems.
