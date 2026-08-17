# Plug Analyzer User Guide

## What it does

Plug Analyzer measures a fluorescent plug in one microscope Z-stack. It runs locally and does not upload data.

The results describe what is visible in the image. They do not prove true porosity or blocked flow. Use a separate flow or pressure test for that.

## What you need

- An untouched TIFF, OME-TIFF, or Nikon ND2 file.
- Correct X, Y, and Z calibration in micrometres.
- A plug-free background area.

## Four-step workflow

### 1. Project

Choose **Create project** and select an empty folder. A project can contain several samples and saved runs.

The Project page also shows the project size. **Show project folder** opens it in Finder or Explorer. **Remove cached image data** removes only rebuildable data after the original image is checked. It does not remove saved results.

### 2. Import

Choose a `.tif`, `.tiff`, or `.nd2` file, then select **Inspect source**.

Check the format, dimensions, image channel, calibration, memory, and free disk space. The original file is never changed. The first analysis creates a lossless cache in the project.

Scene, time, channel, and Z values are zero-based. Inspect the source again after changing any of them.

### 3. Analyze

Use the Z slider and the linked top and side views to inspect the raw image.

1. Check X, Y, and Z calibration, then confirm it.
2. Place the blue region over the channel area to measure.
3. Place the green region over a plug-free background area.
4. Add the amber plug outline only if you need the low-fluorescence estimate.
5. Select **Run analysis**.

The red overlay is the detected plug. Yellow marks uncertain edge pixels. The detection method is fixed in this prototype, so there are no method controls to tune.

After analysis, stay on this screen to review the image and overlays. Select **View results** when ready.

### 4. Results

Review the measurements, notes, warnings, and charts. Select **Save result** only when the result is acceptable. Saved runs do not change; a rerun creates a new result.

You can export CSV, JSON, or PNG files and copy tables.

#### Compare saved app runs

The comparison section uses only results saved by Plug Analyzer in the current project.

1. Choose **Run A**.
2. Choose **Run B**.
3. Select **Compare saved runs**.

The **Change** column is `Run B - Run A`. The app warns when the method, calibration, analysis region, or image channel differs. If image channels differ, intensity change is not shown. Other measurements remain visible with a warning.

Human labels, manual reference values, spreadsheets, and uploaded 3D masks are not part of this prototype. Compare those outside the app if needed.

## Main outputs

| Output | Plain meaning | Important limit |
|---|---|---|
| Area per Z-plane | Detected plug area in each image slice | Depends on calibration and detection |
| Corrected integrated intensity | Background-corrected signal inside the plug | Compare matched image acquisition only |
| Observed volume | Detected plug volume in the captured stack | May be a lower bound at an image edge |
| Maximum occlusion | Largest blocked fraction of the reviewed channel | Describes the image, not flow |
| Minimum open area | Smallest remaining open channel area | Not a direct flow measurement |
| Open path | Whether an image-visible route connects both ends | Not proof of hydraulic flow |
| Bottleneck diameter | Smallest clearance along the widest open route | Limited by image resolution |
| Apparent low-fluorescence fraction | Low-signal volume inside the reviewed plug outline | Image estimate, not true porosity |

## If analysis is blocked

- **Calibration not confirmed:** check the values and confirm them.
- **Background error:** move or enlarge the green region so every slice has enough plug-free pixels.
- **Unsafe resources:** free disk space or close large applications.
- **Source changed:** inspect the intended original file again.
- **ND2 unsupported:** keep the ND2 and make a lossless OME-TIFF or original-bit-depth TIFF export.
