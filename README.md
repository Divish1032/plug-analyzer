# Plug Analyzer Prototype

Plug Analyzer is a local desktop prototype for deterministic measurement of a fluorescent plug in a microscope Z-stack. It imports the selected voxels losslessly, shows the stack and segmentation overlay, calculates qualified measurements, and saves only the runs the user explicitly accepts.

This is a validation tool, not a validated product-efficacy test. A single fluorescence channel cannot prove true material porosity or functional sweat blockage.

## Current status

Version 0.2.2 implements the planned end-to-end prototype workflow:

```text
Create project -> inspect source -> review calibration/ROIs -> analyze
               -> review preview -> save/export -> compare
```

- Four-page macOS/Windows desktop UI built with PySide6.
- Deterministic light-only application palette, controls, viewers, and results pages independent of the operating-system appearance.
- TIFF, ImageJ TIFF, OME-TIFF, multipage TIFF, BigTIFF, and provisional Nikon ND2 readers.
- Read-only source handling, resource preflight, lossless chunked Zarr cache, checksums, cancel, and resume.
- Deterministic 3D background correction, physical Gaussian filtering, hysteresis segmentation, component filtering, metrics, QC, and threshold robustness.
- Linked XY/XZ/YZ raw-image views, plug and uncertain-edge overlays, and editable polygon-prism or rectangular ROIs.
- Visible user-chosen project storage, immutable saved runs, CSV/JSON/PNG export, copyable tables, and comparison between saved app runs.
- Clear warnings when two saved runs use different analysis settings, calibration, regions, or image channels.
- Simple project-folder access and safe removal of rebuildable cached image data.
- Headless `inspect` and small-stack `analyze` commands.
- Native packaging recipes for Apple Silicon macOS and Windows x64.
- The earlier Apple Silicon 0.2.2 DMG passed its packaged dependency smoke, but it predates this workflow cleanup. Build a fresh installer before distributing the simplified UI. A native Windows build still requires executing the completed recipe on Windows x64.

The supplied [`../test.tif`](../test.tif) is accepted as a 62 x 234 x 1024, single-channel, 16-bit ImageJ TIFF with 12 significant bits. Its metadata, selected planes, lossless cache, and deterministic analysis have regression coverage. Those checks prove software consistency only; their segmentation is not human ground truth.

Large-file import is out of core. The GUI automatically chooses the in-memory or exact disk-backed engine from resource preflight. The bounded path processes every selected voxel, uses disk-backed intermediates, streams saved masks, and calculates exact open-path connectivity and bottleneck clearance. Synthetic equivalence tests cover the large path; running a genuine 2-6 GB SME file later is operational acceptance, not unimplemented software.

See [Known limitations](docs/KNOWN_LIMITATIONS.md) before using results with an SME.

## Run from source

Requirements: Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/Divish1032/plug-analyzer.git
cd plug-analyzer
uv sync --frozen --extra dev
uv run plug-analyzer-gui
```

The app creates no account and uploads nothing. Choose an empty, visible folder when creating a project.

Inspect the supplied stack without decoding the complete volume:

```bash
uv run plug-analyzer inspect ../test.tif
```

The CLI analysis command is intended for preflight-approved small stacks. Run `uv run plug-analyzer analyze --help` for its required reviewed ROI and calibration options.

## Project storage

Each project is one ordinary folder:

```text
example.plug-project/
├── project.sqlite       sample and run records
├── data/                rebuildable lossless Zarr caches
├── runs/                immutable saved result tables and plug masks
├── exports/             reserved project export area
├── work/                resumable import and disk-backed analysis state
├── logs/                reserved support logs
└── project-manifest.json
```

The original microscope file remains at its original path and is not modified. The Project page can show the project folder and remove rebuildable cached image data after verifying the original source identity. Saved runs are not removed by this action.

## Documentation

- [SME user guide](docs/USER_GUIDE.md)
- [Functional blockage and SME pilot readiness](docs/FUNCTIONAL_BLOCKAGE_AND_PILOT_READINESS.md)
- [Known limitations](docs/KNOWN_LIMITATIONS.md)
- [Developer guide](docs/DEVELOPER_GUIDE.md)
- [Candidate scientific method](docs/SCIENTIFIC_METHOD_V1.md)
- [Plan v2 and release gates](docs/PLAN_V2.md)
- [Decision log](docs/DECISIONS.md)
- [Prototype scope](docs/PROTOTYPE_SCOPE.md)
- [Research references](docs/RESEARCH_REFERENCES.md)
- [Implementation tracker](TRACKER.md)

## Distribution targets

- Apple Silicon macOS: the existing unsigned internal-pilot DMG is an older verified build and does not include this cleanup. Rebuild and reverify before handoff.
- Windows x64: unsigned internal-pilot `Setup.exe`, which must be built and smoke-tested on native Windows x64.

The prototype is not published through an app store and has no updater, code signing, or notarization yet. Build and verification commands are in [the developer guide](docs/DEVELOPER_GUIDE.md) and [packaging notes](packaging/README.md).

## Manual build and local deployment

Run `make help` from this directory. The shortest safe workflow is `make setup`, `make check`,
`make build`, then `make deploy`. Build and deployment are separate: deployment only verifies and
installs an existing native installer. The commands use the version already declared in
`pyproject.toml` and never increment or rewrite it. See [scripts/README.md](scripts/README.md) for
the explicit macOS and Windows commands.
# plug-analyzer
