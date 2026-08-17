# Functional Blockage, Development Status, and SME Handoff

**Status date:** 16 August 2026  
**Software version:** 0.2.2  
**Scientific protocol:** `candidate-v1-unlocked`

## Current decision

The planned prototype development is complete. It can be handed to SMEs for exploratory TIFF,
OME-TIFF, BigTIFF, ND2, multi-gigabyte, analysis, and saved-run comparison trials. The software work and
the later scientific/manual acceptance work are different gates:

| Gate | Status | Meaning |
|---|---|---|
| Prototype software implementation | **Complete** | The planned desktop, analysis, validation, storage, large-file, and packaging code paths are implemented and automated-test covered. |
| Supplied `test.tif` regression | **Passed** | Import, analysis, orthogonal review, save, export artifacts, and package smoke use the supplied stack. This is not human ground truth. |
| Nikon ND2 implementation | **Complete** | Scene/time/channel/Z selection, metadata, bounded reads, fail-closed errors, and modern/legacy/unsupported/corrupt scenarios are covered with generated reader fixtures. |
| Genuine SME ND2 trial | **Pending manual acceptance** | A real Nikon file is needed to discover vendor/acquisition variants; this is not missing implementation. |
| Large-file implementation | **Complete** | Lossless chunked import, resource preflight, automatic disk-backed analysis, exact connectivity/bottleneck, cancellation boundaries, and streaming save are implemented. |
| Genuine 2–6 GB timing trial | **Pending manual acceptance** | The SME trial records real duration/RAM/disk and may reveal defects; it is not a prerequisite for software-complete status. |
| Saved-run comparison | **Complete** | Two immutable app runs can be compared with Run B minus Run A and clear method, calibration, region, and channel warnings. |
| Apple Silicon installer | **Rebuild required** | The earlier 0.2.2 DMG was verified, but it predates the simplified four-screen workflow. Build and verify a fresh artifact before handoff. |
| Windows x64 installer code | **Complete** | Native Nuitka/Inno recipe and automated checks are present. Producing the binary requires running it on Windows x64. |
| Functional blockage claim | **Not established by imaging alone** | This is a scientific evidence boundary, not a software stub. Flow/pressure evidence is required. |

## Implemented workflow

```text
Project
        ↓
TIFF/ND2 inspect → scene/time/channel/Z selection → RAM/disk preflight
        ↓
XY + linked XZ/YZ review → rectangles or editable polygon ROIs
        ↓
deterministic 3D analysis
        ↓
raw image + plug/uncertain-edge overlays
        ↓
save → CSV/JSON/PNG/copy → compare saved app runs
        ↓
show project folder or safely remove rebuildable cached image data
```

The remaining activities are SME data trials, clean-machine installation, and scientific protocol
decisions. They may generate defect reports, but no known planned prototype feature is deliberately
left as a placeholder.

## Why “porosity” remains an image-based proxy

The app calculates:

\[
P_{app}=100\frac{V(E\cap L\cap \neg M)}{V(E\cap L)}
\]

`E` is the reviewed plug envelope, `L` the lumen, and `M` the fluorescent plug mask. In plain
language, it reports the fraction of the reviewed plug region that is not classified as fluorescent
plug.

A dark voxel can be a liquid-filled pore, but it can also be unlabeled material, weak signal at
depth, photobleaching, quenching, blur, or a threshold effect. A bright region can contain a route
smaller than the optical resolution. The truthful output name is therefore **apparent
low-fluorescence fraction**, not true physical porosity.

This qualification cannot be removed by more application code from the same one-channel image.
It requires additional experimental information.

## Why imaging cannot prove functional blockage

```text
Z-stack evidence                         Flow experiment evidence
plug shape, occlusion, visible paths      flow rate, pressure drop, leakage
                    \                    /
                     combined blockage evidence
```

A static Z-stack does not measure liquid movement, hydraulic resistance, breakthrough with time,
sub-resolution paths, or bypass routes outside the field. Therefore:

```text
No visible route  ≠ guaranteed zero flow
Visible route     ≠ confirmed flowing route
```

For hydraulic blockage, measure baseline and post-plug flow at a declared pressure, or pressure at
a declared flow, plus leakage/breakthrough time and controls. Useful quantities are:

```text
Flow reduction (%) = 100 × (1 − Q_after / Q_before)
Hydraulic resistance = pressure difference / flow rate
Resistance increase = R_after / R_before
```

This establishes blockage only in the tested microfluidic model. A reduced-human-sweating claim
requires the appropriate physiological/ex-vivo/in-vivo pathway agreed with the relevant experts.

## Why protocol/threshold freezing is not a development blocker

The app records every threshold, geometry, correction path, calibration, and algorithm version.
“Freezing” means the SME decides which fixed values and acceptance
tolerances will define the validated scientific method after examining a declared development set.

We should not invent that biological decision from one TIFF. SMEs may use the current candidate
protocol now for exploratory trials. They should not call it a validated efficacy method until the
freeze and held-out validation are complete.

## SME handoff checklist

1. Preserve original microscope files unchanged.
2. Review calibration, ROIs/polygons, orthogonal views, mask, uncertain edge, and QC.
3. Save only accepted previews.
4. Compare saved app runs when useful.
5. Keep any human labels, spreadsheets, or 3D-mask validation in the external validation workflow.
6. Try genuine ND2 and large files and report unsupported metadata, resource refusal, excessive
   duration, crashes, or scientifically incorrect masks as defects.
7. Pair imaging with flow/pressure data before making a functional-blockage claim.

See the [SME user guide](USER_GUIDE.md), [scientific method](SCIENTIFIC_METHOD_V1.md),
[known limitations](KNOWN_LIMITATIONS.md), and [implementation tracker](../TRACKER.md).
