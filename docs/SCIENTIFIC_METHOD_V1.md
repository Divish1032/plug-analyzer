# Scientific Method v1 — Candidate Deterministic Protocol

**Date:** 14 August 2026  
**Status:** Candidate for prototype implementation; threshold/envelope parameters must be locked on development samples before held-out validation.

The domain papers, quantitative-fluorescence guidance, validation methods, and technical sources used here are listed in [Research and Technical References](RESEARCH_REFERENCES.md).

## 1. Scientific position

The closest antiperspirant microfluidic studies support measuring the location, growth, and obstruction caused by fluorescent protein aggregates. They do not provide one universal image threshold, and they do not show that a single-channel dark region is necessarily a physical pore.

The v1 method therefore uses:

- a transparent, deterministic, background-referenced 3D segmentation rule;
- user-reviewed channel geometry;
- raw-value fluorescence measurements;
- explicit boundary, saturation, resolution, and comparability flags;
- parameter-robustness ranges;
- flow/pressure evidence only when claiming functional blockage.

## 2. Required inputs and acquisition gate

For each selected analysis volume, record:

- source file fingerprint and reader/version;
- scene/position, time point, channel, axis order, dimensions, and orientation;
- dtype, significant bits, detector maximum when known, and saturated-pixel fraction;
- `s_x`, `s_y`, `s_z` and units, including per-plane Z coordinates when available;
- fluorophore/label identity and what the label represents;
- laser/excitation, detector gain/offset, objective/NA, pinhole, zoom, dwell time, averaging, acquisition timestamp, and Z acquisition order when available;
- whether a matching dark, flat-field, pre-contact, or soluble-tracer stack exists;
- whether the full plug and the complete lumen cross-section are captured.

Block physical-unit outputs if calibration is absent. Allow manual calibration only with a permanent “manual” provenance flag.

For cross-sample fluorescence comparison, acquisition settings and sample chemistry must be compatible. Missing or different settings produce a warning and may block pooled intensity statistics.

## 3. Geometry model

Save the following reviewed geometry with a version:

- `L`: 3D lumen mask;
- `u`: unit vector along the straight sweat-duct channel;
- `r0`: reference point/junction position;
- inlet and outlet faces;
- plug analysis range along the duct;
- background/unaggregated-lumen reference ROI;
- optional plug envelope `E` for apparent low-fluorescence analysis.

The app may propose these features, but the SME reviews them. Structural wall pixels outside `L` are excluded. The lumen-adjacent band inside `L` is retained so real wall-nucleated plug growth is not automatically removed.

For a curved channel in future data, reslicing along a centerline can be added later. The v1 assumption is a straight or nearly straight channel.

## 4. Intensity correction

Let `I(z,y,x)` be original source intensity.

### 4.1 Dark/flat correction, only with proper calibration images

If a detector-dark image `D` and a normalized flat field `F` exist:

\[
I_f = \frac{I-D}{F}
\]

Reject zero/invalid flat-field pixels. Do not estimate a flat field from the single static plug stack: a spatially correlated foreground can be mistaken for illumination shading.

Without valid calibration images, set `I_f = I` and record that no flat-field correction was applied.

### 4.2 Preferred pre-contact subtraction

Use pre-contact subtraction only when channel geometry, fluorescence channel, voxel calibration, and acquisition settings match. The v1 registration is deliberately limited to a 3D translation; it does not scale, deform, or rotate the data. Estimate the shift from stable lumen walls/a structural reference region or a separate structural channel, never from the growing plug ROI.

Keep the post-contact stack on its original measurement grid. Resample only the pre-contact baseline onto that grid using documented trilinear interpolation in physical coordinates and retain floating-point values. Define an overlap mask; do not extrapolate outside the shared volume and do not measure interpolation-edge pixels. Then calculate an initial difference within the accepted overlap:

\[
J_0 = I_{post,f} - I_{pre,f}
\]

This is preferred because wall adsorption or baseline fluorescence can otherwise be misclassified as new plug material. It is accepted only when all of the following pass a locked Phase 0 rule:

- source settings/calibration are compatible;
- translation magnitude and shared-volume fraction are within approved ranges;
- residual wall/reference misalignment is below an approved physical-unit error;
- no material geometry change is visible outside the plug region;
- an overlay is visually approved.

Store the transform, interpolation, overlap fraction, residual error, and reviewer decision. If registration fails, if a rotation is required, or if photobleaching/gain changes make subtraction invalid, do not force it; fall back to the reviewed reference-background method and flag the correction path. Results using different correction paths are not pooled for intensity comparison without explicit review.

### 4.3 Fallback reference-background correction

Without an accepted pre-contact stack, set `J_0 = I_f`. Then, in both paths, remove any residual per-plane offset using the reviewed reference region:

\[
b_z = \operatorname{median}(J_0 \text{ within the reviewed reference ROI at } z)
\]

\[
J(z,y,x) = J_0(z,y,x)-b_z
\]

The protocol locks a minimum valid reference area and pixel count for every analyzed plane. A candidate engineering default is at least 1,000 valid pixels per plane, subject to development-data review. Detector-invalid and saturated pixels are excluded. A plane with an absent, visibly contaminated, or undersized ROI is not silently interpolated from neighboring planes; the user selects another reviewed ROI or the run is blocked. Multiple approved reference ROIs may be used to test background sensitivity.

For raw-data QC, estimate residual background noise over the combined valid reference samples:

\[
\sigma_{B,raw} = 1.4826 \times \operatorname{MAD}(J_{reference})
\]

Do not clip negative `J` values when calculating integrated fluorescence; clipping creates positive bias. A non-negative working copy may be used only for segmentation and display.

No photobleaching or depth-attenuation correction is inferred from the plug's own Z profile. Such a correction is allowed only when a homogeneous control acquired under matching conditions supports it.

## 5. Segmentation

### 5.1 Working image

1. Restrict to `L` and the reviewed axial analysis range.
2. Create a segmentation-only image `J_seg` with minimal 3D denoising.
3. Express filter width in micrometers and convert it per axis using `s_x`, `s_y`, `s_z`.
4. Keep the filter below the measured/resolution-supported feature scale.

Raw corrected `J`, not `J_seg`, is used for fluorescence measurements.

Estimate threshold noise after applying the identical segmentation filter to the reference voxels:

\[
\sigma_{B,seg}=1.4826\times\operatorname{MAD}(J_{seg,reference})
\]

This keeps the noise scale consistent with the filtered threshold image. Save both raw and filtered noise estimates, reference-ROI size by plane, and contamination checks.

### 5.2 Candidate default: locked 3D hysteresis

Use two fixed multiples of the same robust background noise estimate:

\[
Seed = J_{seg} \ge k_H\sigma_{B,seg}
\]

\[
Candidate = J_{seg} \ge k_L\sigma_{B,seg}, \qquad k_L < k_H
\]

The preliminary plug mask contains candidate voxels connected in 3D to at least one seed voxel.

`k_L`, `k_H`, denoising width, and minimum physical component volume are chosen on the development set, documented, and frozen. Hysteresis is recommended because it can retain dim parts of a connected aggregate without accepting every dim background voxel.

### 5.3 Development baseline

Also test a single threshold `J_seg >= k * sigma_B_seg` and one 3D Otsu threshold during Phase 0/1. Otsu is computed once over the 3D analysis ROI, never separately for each Z-plane. These are method-development comparators, not three freely interchangeable validated protocols.

The chosen protocol is locked before held-out validation. Saved results always include the protocol identifier and exact parameters.

### 5.4 Physical post-processing

- Use 6-neighbour connectivity for conservative 3D component decisions.
- Also calculate the relevant connectivity decision with 26 neighbours as a sensitivity check; if the result changes, flag “connectivity ambiguous.” Synthetic rotated-channel fixtures must quantify orientation sensitivity.
- Remove only components smaller than a locked minimum volume in µm³.
- Use anisotropic structuring elements defined in physical units.
- Do not fill internal holes or apparent passages by default.
- Clip the mask to `L` and the analysis range.
- Review the overlay before accepting a run.
- Chunked and in-memory binary masks must match exactly on test fixtures.

## 6. Metric definitions

Let `M` be the final plug mask. For a uniform Z-stack, voxel volume is `v = s_x s_y s_z`. If native metadata supplies non-uniform plane positions, derive each plane's represented thickness from midpoint boundaries between adjacent Z centers (with the nearest interval extrapolated by half at the two ends) and use `v_z = s_x s_y Δz_z`. Duplicate or non-monotonic Z positions block volume/cross-section calculations until resolved.

### 6.1 Per-Z measurements

Plug area:

\[
A_z = \sum_{x,y}M(z,y,x)\,s_xs_y \quad [\mu m^2]
\]

Requested corrected integrated intensity (ImageJ-style summed pixel intensity):

\[
CII_z = \sum_{x,y}M(z,y,x)\,J(z,y,x) \quad [\text{summed corrected AU}]
\]

Spatial area-weighted fluorescence integral:

\[
FI_{A,z}=\sum_{x,y}M(z,y,x)\,J(z,y,x)\,s_xs_y
\quad [\text{corrected AU}\cdot\mu m^2]
\]

Mean corrected intensity, when the mask is non-empty:

\[
\bar{J}_z = \frac{CII_z}{\sum_{x,y}M(z,y,x)}
\]

Area, mean intensity, and integrated intensity are reported separately; one must not be used as a hidden substitute for another.

Across the captured 3D region, also report:

\[
FI_V=\sum_z\sum_{x,y}M(z,y,x)\,J(z,y,x)\,s_xs_y\Delta z_z
\quad [\text{corrected AU}\cdot\mu m^3]
\]

`CII_z` is retained for direct compatibility with the requested/ImageJ-style measurement. `FI_A,z` and `FI_V` are numerical spatial integrals. None is automatically a material amount. Different pixel size, Z sampling, gain, laser, dwell time, pinhole, fluorophore chemistry, or pH can change their meaning; comparisons are blocked unless the acquisition protocol is compatible or a valid calibration model exists. Multiplying by pixel/voxel size does not by itself repair an incompatible acquisition.

### 6.2 Observed 3D volume

\[
V_{observed} = \sum_z\sum_{x,y} M(z,y,x)\,s_xs_y\Delta z_z \quad [\mu m^3]
\]

If the plug touches the X/Y field boundary or the Z-stack does not contain its full depth, label this “observed volume within the imaged region,” not total plug volume.

### 6.3 Axial position and penetration

For physical voxel coordinate `r`:

\[
q=(r-r_0)\cdot u
\]

Report:

- maximum retained plug extent `q_max` after the physical component-size rule;
- robust 95th percentile extent `q_95` to reduce sensitivity to isolated terminal voxels;
- position of maximum cross-sectional occlusion.

If the plug reaches an image boundary along the duct, penetration is reported as `>= observed extent`.

### 6.4 Cross-sectional blockage

Bin voxels along `q` using a locked physical bin width `Δq`. This avoids unnecessary interpolation and conserves voxel volume.

\[
A_P(q)=\frac{1}{\Delta q}\sum_{q\ bin}M\,v_z
\]

\[
A_L(q)=\frac{1}{\Delta q}\sum_{q\ bin}L\,v_z
\]

\[
Occlusion(q)=100\frac{A_P(q)}{A_L(q)}
\]

\[
A_{open}(q)=A_L(q)-A_P(q)
\]

Report the full curves plus maximum occlusion, mean occlusion over the reviewed plug range, minimum remaining open area, and their positions.

Disable or qualify these metrics if the full lumen cross-section is not captured.

### 6.5 Connected open path and bottleneck clearance

\[
Open = L \land \neg M
\]

Use 6-neighbour 3D connectivity as the conservative primary decision and 26-neighbour connectivity as a sensitivity result. If only the 26-neighbour graph connects inlet to outlet, report “diagonal/sub-resolution connectivity ambiguous,” not simply open.

Calculate an anisotropic Euclidean distance transform inside `Open` using physical voxel spacing. Find the inlet-to-outlet path that maximizes its minimum distance to plug/lumen boundaries. Report twice that minimum distance as the image-resolved bottleneck diameter.

A one-voxel or sub-resolution route is flagged unreliable. An image-resolved path is not proof of flow, and no detected path is not proof of a perfectly sealed molecular-scale barrier.

### 6.6 Apparent low-fluorescence fraction

This is the allowed single-channel proxy for the requested porosity measurement:

\[
P_{app}=100\frac{V(E\cap L\cap \neg M)}{V(E\cap L)}
\]

`E` is a reviewed plug envelope. The candidate automatic envelope is a fixed physical-radius 3D closing of retained plug components, clipped to `L`; its radius is locked and included in robustness analysis. If a defensible envelope cannot be formed, report the metric as unavailable.

Always label the result **apparent low-fluorescence fraction**, never true porosity. It can include unlabeled material, quenching, dim signal, blur, and sub-resolution structure. A second soluble-tracer channel would support tracer-accessible void fraction; flow or pressure is still needed for functional sealing.

### 6.7 Additional diagnostics

- Wall-associated plug fraction: fraction of `M` within a locked, resolution-supported distance from the lumen wall.
- Largest-component fraction: volume of the largest retained component divided by total plug-mask volume.
- Saturated-pixel fraction inside `M`, overall and by Z-plane.
- Background SNR and contrast-to-background statistics.
- Fraction of plug/envelope touching each image boundary.
- Acquisition-setting compatibility status for every comparison group.

## 7. Quality and availability flags

Every result carries one of: `valid`, `valid with warning`, `lower bound`, `within imaged volume only`, or `not available`.

Minimum automatic flags:

- missing/manual calibration;
- duplicate, non-monotonic, or materially non-uniform Z coordinates;
- missing fluorescence identity;
- saturation above the SME-approved limit;
- plug touches X/Y boundary;
- plug signal present in first or final Z-plane;
- incomplete lumen cross-section;
- low background ROI size or contaminated background;
- pre-contact registration failed/fell back, or correction paths differ across a comparison;
- acquisition settings missing/different across compared samples;
- segmentation sensitivity outside tolerance;
- extended robustness not run for a result being used as a validation sample;
- open path narrower than measured optical resolution;
- source changed since import;
- manual mask/geometry edits present.

## 8. Robustness and uncertainty

Two modes keep routine work fast without hiding parameter sensitivity:

- **Standard analysis:** primary mask plus the locked low/high threshold variation; required for every finalized run.
- **Extended validation:** the full set below; required for held-out validation samples and optional for rapid exploratory samples.

Extended validation recalculates metrics over predeclared valid variations such as:

- low/high threshold parameters around the locked value;
- alternative reviewed background ROIs;
- minimum component volume;
- lumen boundary eroded/dilated by one measured resolution element;
- plug-envelope radius;
- Z calibration range when axial scaling is uncertain.

Report the minimum/maximum result as a **parameter robustness interval**, not a statistical confidence interval. Candidate threshold variation for the first pilot is ±10%, subject to SME approval during method lock. Variants execute sequentially, reuse scratch storage, and persist parameters plus scalar outcomes rather than a full mask for every variant.

Biological uncertainty is estimated across independent experimental samples, not across voxels or Z-planes. Z-planes from one stack are repeated spatial observations of the same sample.

## 9. Manual validation without spreadsheet ingestion

The SME may type a reference value for any scalar result. Store:

- exact metric definition, reference value, and unit;
- reviewer, reference method, date, tolerance, and notes.

Per sample:

\[
e = Estimate-Reference
\]

\[
AE = |e|
\]

\[
PE = 100\frac{e}{Reference}
\]

Percentage error is omitted when the reference is zero or too close to zero for a meaningful ratio.

Across independent samples, always report the paired table, bias, MAE, and RMSE. Correlation alone is not agreement.

With fewer than 20 independent paired samples, do not present Bland–Altman limits of agreement or Lin's concordance as if stable; keep the summary exploratory. At 20 or more, show them with bootstrap 95% confidence intervals and a difference-versus-magnitude diagnostic. If error variance changes with magnitude, use only the transform or stratification predeclared in the locked statistical plan. Formal acceptance requires the Phase 0 sample-size target based on acceptable error/limits-of-agreement precision and expected variability. The `n=20` UI threshold is a safeguard, not a universal adequate sample size.

Per-Z automated curves are exported as CSV for external SME comparison. The v1 app does not parse arbitrary spreadsheet layouts.

## 10. Optional mask validation

Not required for initial use. If reviewed masks later become available, calculate in physical 3D space:

- Dice and IoU;
- precision and recall;
- absolute/relative volume difference;
- average symmetric surface distance;
- 95th percentile Hausdorff distance (HD95).

A small independent mask subset is recommended because scalar agreement can coexist with a spatially wrong segmentation. Experts should create the initial mask without seeing the automatic outline when practical, to reduce anchoring bias.

## 11. Interpretation constraints

- Corrected fluorescence is a relative proxy for labeled material, not automatically antiperspirant mass, protein mass, or density.
- If the label is FITC/FITC-BSA, local pH can strongly alter brightness; formulations with different pH need matrix-matched calibration before intensity is interpreted as amount.
- Saturated pixel values are lower bounds; lost intensity cannot be reconstructed.
- Confocal PSF blur and anisotropic Z sampling limit resolvable passages and surface boundaries.
- Refractive-index mismatch can change axial scale, blur, and intensity with depth.
- Deconvolution is deferred from the default protocol. If later added, it must use a measured PSF, be validated, and influence mask generation only; intensity remains measured from corrected raw data.
- Imaging describes morphology and obstruction proxies. Flow, pressure drop, or hydraulic resistance is needed to validate clogging performance.

## 12. Current `test.tif` limitations

The current stack is sufficient for implementing file reading, views, area/intensity curves, preliminary masks, and numerical tests. It is not by itself a validation dataset.

- The structure continues beyond the right image boundary, so complete length and exact penetration are censored.
- Signal remains near stack boundaries; full top-to-bottom plug coverage must be confirmed.
- Until complete lumen capture is confirmed, cross-sectional occlusion and connected-path results must be labelled “within imaged volume only” or unavailable.
- Low but non-zero saturation means affected integrated intensity is a lower bound.
- Fluorescence identity and acquisition settings remain required before biological interpretation.

## 13. Method-lock gate

Before calling a protocol “Validated v1,” the SME and developer must record:

- development, validation, and optional blind-test sample IDs;
- background method and ROI rule;
- pre-contact eligibility, registration transform/QC, and fallback rule;
- filter type/physical scale;
- chosen segmentation rule and all thresholds;
- connectivity and minimum physical component volume;
- lumen/axis/junction/envelope rules;
- metric bin widths and availability conditions;
- robustness variations;
- acceptance tolerances;
- independent-sample target, confidence intervals, and heteroscedasticity policy;
- known acquisition limitations.

The application stores this as an immutable, versioned protocol configuration. Changing any scientific parameter creates a new protocol version and a new analysis run.
