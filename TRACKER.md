# Implementation Tracker

**Last updated:** 14 August 2026  
**Overall status:** Planned version-0.2.2 prototype development complete; 132 automated tests and supplied-TIFF regression pass. The verified Apple Silicon 0.2.2 DMG is ready. Genuine ND2/large-file trials, scientific protocol lock, native Windows execution, and clean-machine checks are later manual acceptance.

`[x]` means implemented and exercised in the repository. It does not mean scientifically validated by an SME dataset or released on both operating systems.

## Foundation and method

- [x] Characterize the supplied `test.tif` and preserve it as read-only input.
- [x] Receive SME agreement to prototype the proposed measurement direction.
- [x] Persist architecture, scientific method, decisions, and research references.
- [x] Implement the deterministic candidate protocol and explicit result qualifications.
- [ ] Freeze thresholds, geometry rules, availability rules, and tolerances on a declared development set.
- [ ] Obtain representative weak/medium/strong samples and a held-out validation set.
- [ ] Confirm fluorophore meaning, matched acquisition settings, and complete lumen/plug capture.
- [ ] Deferred: obtain a pre-contact/control stack only if the reconsideration criteria in `docs/PROTOTYPE_SCOPE.md` are met.

## Scientific engine

- [x] Per-plane reviewed-background subtraction without clipping negative corrected values.
- [x] Physical-unit 3D Gaussian filtering and robust MAD noise estimate.
- [x] Deterministic 3D hysteresis and physical component-volume filtering.
- [x] Per-Z area, corrected integrated intensity, fluorescence area integral, and mean intensity.
- [x] Observed volume, fluorescence volume integral, axial extent, and cross-section curves.
- [x] Image-resolved open-path connectivity and exact in-memory/disk-backed bottleneck clearance.
- [x] Apparent low-fluorescence fraction when a reviewed envelope is supplied.
- [x] Saturation/boundary/connectivity QC and predeclared threshold robustness runs.
- [x] Translation-only pre/post registration primitive with overlap and fail-closed QC tests.
- [x] Implement paired pre-contact registration, compatibility/QC, reviewer approval, and subtraction; its UI is intentionally disabled for the current SME prototype.
- [x] Add editable non-rectangular polygon-prism analysis/lumen, background, and envelope ROIs with undo/redo; retain the documented straight cardinal-X terminal assumption.
- [ ] Lock and validate the candidate protocol against SME ground truth.

## File handling and resources

- [x] TIFF, ImageJ TIFF, OME-TIFF, multipage TIFF, and BigTIFF probe/read adapters.
- [x] Provisional modern and legacy Nikon ND2 adapter with scene/time/channel/Z selection model.
- [x] Preserve normalized metadata, raw vendor metadata, calibration provenance, and source fingerprint.
- [x] Lossless chunked Zarr cache with per-chunk checksums and bit-equality verification.
- [x] RAM/disk preflight, deterministic cache chunk plan, cancellation, and resumable import.
- [x] Reject source changes and corrupt/incompatible cache reuse.
- [x] Exact disk-backed candidate analysis with automatic memory-based selection, virtual ROIs, explicit project workspace, streaming mask save, and small-fixture equivalence tests.
- [ ] Acceptance-test genuine Nikon ND2 files from the laboratory.
- [ ] Acceptance-test a genuine 2-6 GB stack with measured RAM/disk high-water use.
- [x] Verify deterministic in-memory versus disk-backed results, including chunk seams and exact connectivity/bottleneck, using generated bounded fixtures.
- [ ] Record cancellation/timing/RAM/disk behavior on a genuine large laboratory file (manual acceptance).

## Desktop workflow

- [x] Project, Import, Analyze, and Results pages.
- [x] Linked XY/XZ/YZ raw-image viewer; display levels; plug and uncertain-edge overlays.
- [x] Draggable rectangles plus editable polygon-prism ROIs with create/erase/undo/redo.
- [x] Calibration confirmation, ROI/threshold inputs, progress, cooperative cancellation, and close safety.
- [x] Result table, per-Z area/intensity charts, QC text, and availability qualifications.
- [x] Explicit immutable Save Result flow and local CSV/JSON export.
- [x] Automatic method, calibration, region, and channel checks for saved app-run comparison.
- [x] Pairwise saved-run comparison with Run B minus Run A and plain-language metric labels.
- [x] Exact-grid binary 3D human-mask validation with Dice, IoU, precision, recall, volume difference, ASSD, and HD95.
- [x] Remove typed SME reference, cohort, and 3D-mask validation from the prototype UI and code.
- [x] Single-writer project lock with read-only fallback.
- [x] Visible storage summary, folder/log access, cache/preview/work cleanup, project-copy preparation, and settings reset.
- [x] Confirmed saved-run deletion and recoverable whole-project move to Trash.
- [x] GUI selectors for scene, time point, channel, and Z range with reinspection on change.
- [x] Force a deterministic light-only palette for pages, controls, scrollbars, sliders, and viewer surroundings, independent of the OS theme.

## Verification

- [x] Current macOS development gate: Ruff format/lint clean and 132 tests passed headlessly on 14 August 2026.
- [x] Unit tests for models, corrections, segmentation, metrics, QC, robustness, validation helpers, and exports.
- [x] I/O tests for TIFF variants, mocked multidimensional ND2, cache verification, cancellation, and resume.
- [x] GUI/controller tests for the four-page workflow, project safety, source mutation, result saving, and app-run comparisons.
- [x] Supplied-TIFF acceptance for metadata, selected plane reads, cache equality, and deterministic regression mask.
- [x] CLI inspect/analyze workflow tests.
- [x] Packaging-script, icon, provenance, checksum, and release-verifier tests.
- [x] Automated ND2 compatibility tests for multidimensional selection, unsupported axes, corrupt metadata, fake extensions, and fallback diagnostics.
- [ ] Genuine ND2 acceptance.
- [ ] Large real-stack acceptance.
- [ ] Clean-machine macOS installation test.
- [ ] Clean-machine Windows installation/uninstallation test.

## Packaging and handoff

- [x] Locked Python dependency file and source package entry points.
- [x] Apple Silicon Nuitka standalone + DMG build recipe.
- [x] Windows x64 Nuitka standalone + Inno Setup build recipe.
- [x] Release manifest, SHA-256, build provenance, notices, and smoke checklist tooling.
- [x] SME user guide, developer guide, and known-limitations note.
- [x] Produce and verify the Apple Silicon 0.2.2 pilot DMG from frozen source, including compiled-app and mounted-DMG smoke tests with the supplied TIFF.
- [ ] Build and verify the Windows x64 `Setup.exe` on native Windows x64.
- [ ] Decide whether unsigned pilot security prompts are acceptable or signing is required.

## Manual/SME acceptance queue (not missing development)

1. SME reviews the overlay and candidate outputs for representative samples and labels defects/ground truth.
2. Freeze `protocol-v1` only when the SME chooses the validated parameters and tolerances.
3. Exercise genuine Nikon ND2 variants and a genuine multi-gigabyte stack; record compatibility and resource/timing results.
4. Clean-machine test the macOS installer and execute/build/smoke-test the completed Windows recipe on Windows x64.
5. Pair image morphology with flow/pressure experiments before claiming functional blockage.

## Session log

### 2026-08-14 - End-to-end prototype implementation

- Implemented the local project, I/O/cache, deterministic engine, GUI/controller, export/comparison, and packaging foundations.
- Accepted the supplied TIFF as a software regression input; no output was labelled human ground truth.
- Added automatic reference/disk-backed engine selection and small-fixture equivalence coverage; genuine multi-gigabyte acceptance remains pending.
- Replaced the stale planning handoff with current user, developer, limitation, and tracking documentation.
- Simplified comparison to saved app runs only; external reference validation remains outside the app.
- Added linked orthogonal review, processing-stage display modes, uncertainty overlay, editable polygon-prism ROIs, and chart/table export/copy.
- Added exact disk-backed bottleneck calculation and visible storage lifecycle actions.
- Fixed OS dark-palette leakage by applying a complete light palette at application startup and explicit light styling to controls, scroll areas, viewers, and Results.
- Added a dark-system-palette regression and visually verified Analyze/Results renders; the complete gate is 132 tests.
- Built and deep-verified the unsigned Apple Silicon 0.2.2 DMG; both compiled-app and read-only mounted-DMG smokes passed with the supplied TIFF.
- Recorded DMG SHA-256 `5e855172891158fad3d8e4141904670ab9846d45e78ef3a379a2281987814483` and release support files under `dist/release/0.2.2/macos-arm64/`.
- Installed 0.2.2 in `/Applications` with stable bundle identifier `com.pluganalyzer.prototype`, removed duplicate staged app registrations, refreshed Launchpad, and passed the installed-app smoke test with the supplied TIFF.
- Documented the functional-blockage evidence boundary and explicit Mac/Windows, ND2, large-file, and comparison pilot-readiness decisions.
