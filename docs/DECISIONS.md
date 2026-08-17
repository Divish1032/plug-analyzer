# Decision Log

**Updated:** 16 August 2026

| ID | Status | Decision | Reason / consequence |
|---|---|---|---|
| D-001 | Confirmed | Build a local desktop application. | The data stays on the user's computer; no server, cloud, or telemetry. |
| D-002 | Confirmed | Use Python 3.12, PySide6/Qt Widgets, PyQtGraph, and the scientific Python stack. | Fastest practical path to a cross-platform scientific prototype with native installers. |
| D-003 | Implemented | Make Nikon ND2 and TIFF-family files first-class v1 inputs. | ND2 is the likely Nikon AX/NIS-Elements native source; the current TIFF remains supported. |
| D-004 | Confirmed | Do not bundle Bio-Formats in v1. | Avoid Java, packaging, diagnostics, and licensing complexity until real additional vendor formats require it. |
| D-005 | Confirmed | Normalize the selected analysis volume losslessly into a visible project-local Zarr cache. | Predictable out-of-core access while retaining every selected voxel and original dtype. |
| D-006 | Revised/implemented | Use one bounded in-process Qt background job with cooperative cancellation. | Avoids transferring large arrays or adding a service/process pool. Project-generation guards and non-finalized visible work protect state; native-crash isolation is not claimed. |
| D-007 | Confirmed | Preflight RAM and disk, then adapt chunk size/concurrency. | A 5–6 GB source must not be loaded wholesale or crash the machine. No data may be dropped. |
| D-008 | Confirmed | Store all scientific artifacts in a user-chosen visible project folder. | Storage is understandable, portable, and explicitly deletable. Only small disclosed UI settings live in the OS settings folder. |
| D-009 | Confirmed | No authentication or user model. | One installation is used locally by whoever operates that computer. |
| D-010 | Confirmed | Save finalized analyses only on explicit user action; saved runs are immutable. | Prevents accidental overwrites and makes comparisons reproducible. Work drafts may exist but are clearly labelled and deletable. |
| D-011 | Revised | Keep comparison between immutable app runs only. | Run-to-run review is useful in the prototype. Human references and spreadsheets stay outside the app. |
| D-012 | Removed from prototype | Do not accept human 3D masks in the app. | Mask upload and validation added a second workflow that is not needed for the current prototype. |
| D-013 | Candidate implemented | Use a background-referenced deterministic 3D segmentation protocol selected on development samples. | No paper supplies a universal threshold. The software records the candidate protocol; the SME freeze remains a later scientific decision. |
| D-014 | Confirmed | Report “apparent low-fluorescence fraction,” not true porosity. | A single fluorescence channel cannot distinguish unlabeled material, quenching, or sub-resolution voids. |
| D-015 | Confirmed | Use occlusion, remaining open area, and image-resolved open path as morphology-based clogging indicators. | They are closer to obstruction than plug area alone, but still do not replace flow/pressure validation. |
| D-016 | Confirmed | No machine learning in v1. | Establish deterministic baseline performance and ground-truth practice first. |
| D-017 | Confirmed | Deliver Apple Silicon macOS DMG and Windows x64 Setup.exe. | Matches the current Mac and SME Windows laptops. Intel Mac is deferred. |
| D-018 | Confirmed | Do not target App Store/Microsoft Store. | Internal file distribution is sufficient. Signing remains an optional later hardening step. |
| D-019 | Confirmed | Build separately on each target OS. | Scientific binary dependencies and installers should be tested in their native environments; no macOS-to-Windows cross-build. |
| D-020 | Implemented | Use Nuitka standalone mode inside one installer rather than a runtime-extracting onefile executable. | More predictable startup and dependency behavior while still giving the user one DMG/Setup.exe artifact. |
| D-021 | Implemented/manual acceptance open | Treat ND2 support as provisional until genuine laboratory files pass acceptance tests. | Unsupported or ambiguous ND2 fails closed with a diagnostic; the documented fallback is an SME export to OME-TIFF/lossless original-bit-depth TIFF. |
| D-022 | Implemented candidate | Every saved candidate run gets fixed ±10% threshold sensitivity and a disagreement mask. | Additional geometry/background variants require the SME to declare a validation protocol rather than the app inventing biological perturbations. |
| D-023 | Implemented | Guard agreement statistics by independent sample count and uncertainty reporting. | Below 20 pairs show exploratory error summaries only; formal acceptance uses a predeclared sample-size/precision plan, not correlation. |
| D-024 | Implemented | Use four screens and show the raw image with overlays only. | Removing the processed-image dropdown, acquisition form, and separate Storage screen keeps the pilot focused on import, analysis, results, and saved-run comparison. |

## Open decisions for Phase 0

1. Exact untouched Nikon source format(s) and variants present in the lab.
2. Fluorescent label identity and the physical meaning of signal intensity.
3. Whether pre-contact, dark/flat, or tracer stacks can be added to the acquisition protocol.
4. Whether the full plug and complete lumen cross-section are captured in typical stacks.
5. Final segmentation method/parameters after development-set comparison.
6. Plug-envelope definition and whether apparent low-fluorescence fraction is sufficiently stable to release.
7. SME scalar definitions and acceptance tolerances.
8. Exact Windows version, RAM, and CPU used for acceptance testing.
9. Whether internal OS security prompts are acceptable or code signing is required for pilot distribution.
