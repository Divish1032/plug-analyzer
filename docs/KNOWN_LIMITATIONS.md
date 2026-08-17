# Known Limitations

Read this before interpreting or distributing prototype results.

## Scientific interpretation

- The segmentation and measurements are deterministic estimates, not human-labelled ground truth. External validation is still needed on representative and held-out samples.
- A single fluorescence channel cannot establish true material porosity. The app uses the qualified term **apparent low-fluorescence fraction**, and only when a reviewed plug envelope exists.
- Plug area, occlusion, remaining open area, open-path connectivity, and bottleneck clearance are image-morphology indicators. They do not prove functional sweat blockage, flow, pressure, or hydraulic resistance.
- Integrated intensity is relative. It is comparable only when fluorophore chemistry and acquisition settings are compatible.
- Boundary contact makes some volume/extent results lower bounds or measurements within the imaged volume only.
- Optical resolution, blur, quenching, unlabeled material, saturation, and incomplete capture can change apparent plug/open regions.
- The protocol is still `candidate-v1-unlocked`; thresholds and SME acceptance tolerances are not yet frozen on a representative dataset.

## Geometry and workflow

- Connectivity and bottleneck terminals currently assume a straight channel running along the reviewed cardinal-X direction. The editable ROI can be non-rectangular, but a truly curved centreline/terminal-surface model is not inferred automatically.
- Rectangles and editable polygons are Z-invariant prisms. The SME must check that one XY outline remains appropriate across the selected Z range; per-plane brush painting is not provided.
- If no explicit background rectangle is entered, the prototype uses the top 10% horizontal image band. This convenience default is not a scientifically reviewed background selection.
- The viewer provides linked XY/XZ/YZ planes, not volume rendering.
- Pre-contact correction is not exposed in the current SME prototype. If it is reintroduced, its existing translation-only registration approach would require matching geometry/acquisition and would not correct rotation, deformation, or photobleaching.
- One run still analyzes only one selected scene, time point, channel, and Z range. Each additional selection is imported as another sample/run.

## Files and large data

- TIFF-family readers are covered by synthetic tests and the supplied ImageJ TIFF. Nikon ND2 support is provisional because no genuine laboratory ND2 file has passed acceptance. Legacy/JPEG2000 behavior also remains unverified on real data.
- Preserve any unsupported ND2. The safe fallback is an SME-created lossless OME-TIFF or original-bit-depth TIFF export with metadata; never use JPEG/PNG for quantitative input.
- Lossless import/cache is chunked and resumable. The GUI can automatically select an exact disk-backed candidate scientific path when the reference path exceeds its memory budget.
- The disk-backed path is integrated and has exact small-fixture equivalence tests, including open-path and bottleneck results, but it has not been manually timed on a genuine 2-6 GB source. An interrupted scientific analysis is restartable after visible workspace cleanup; it is not resumed halfway as a finalized run.
- No real multi-position/multi-channel ND2, corrupt real ND2, or genuine 2-6 GB microscope stack has been acceptance-tested.

## Validation and comparison

- The app compares only immutable runs saved by Plug Analyzer in the same project.
- Change is Run B minus Run A. Method, calibration, and analysis-region differences produce warnings instead of hiding the run measurements.
- Intensity change is not shown when image channel names differ.
- Human labels, manual SME values, cohort statistics, spreadsheets, and 3D mask upload are outside the prototype. They can be compared in a separate validation tool.
- The prototype uses deterministic algorithms only. There is no machine learning, training, or automatic learning from SME corrections.

## Storage and distribution

- Scientific work runs as one bounded in-process Qt background job. Cooperative cancellation keeps the UI responsive at safe boundaries, but a fatal native-library crash is not isolated in a separate process.
- The original source stays outside the project. Moving it can prevent safe cache rebuild or checksum-gated cache deletion.
- Disk-backed scientific workspaces remain visible under `work/`. Advanced cleanup is done directly in the visible project folder.
- The Project page can show the folder and safely remove the current sample's rebuildable image cache. It does not delete saved runs or the project.
- Only one process can write a project at a time; another instance opens read-only.
- Apple Silicon and Windows x64 are separate native builds. A Windows `Setup.exe` must be built and smoke-tested on native Windows x64; macOS cannot certify it.
- Internal pilot installers are unsigned. Gatekeeper or SmartScreen may show normal security warnings. App-store delivery, automatic updates, notarization, Authenticode signing, and Intel Mac support are not included.

## What would clear the main limits

1. Freeze the candidate method with the SME on a declared development set.
2. Validate on independent labelled samples and add flow/pressure evidence for functional-blockage claims.
3. Acceptance-test untouched Nikon ND2 examples and a genuine multi-gigabyte stack.
4. Record genuine large-file resource/timing results and complete native clean-machine installer tests.
