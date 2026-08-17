# Plug Analyzer clean-machine smoke checklist

Use a machine that has never had the development environment installed. Record the app version,
installer SHA-256, operating-system version, CPU, RAM, free disk, tester, and date with the test
result. Keep failed observations; do not overwrite them with a later passing run.

## Before installation

- [ ] Confirm the target is Apple Silicon macOS or Windows x64 as named by the installer.
- [ ] Compare the installer SHA-256 with the supplied `SHA256SUMS.txt`.
- [ ] Confirm enough free disk for the installer, project, decoded source, cache, and temporary
      processing estimate shown by the release notes.
- [ ] Confirm Python, a compiler, and administrator/developer tools are not required.

## Install and first launch

- [ ] Install using the normal platform UI; record any Gatekeeper or SmartScreen warning exactly.
- [ ] Launch from Applications (macOS) or the Start menu (Windows), not from source code.
- [ ] Confirm one app window opens without a terminal window or missing-library dialog.
- [ ] Confirm the app version and visible project/settings storage locations are correct.
- [ ] Confirm cancel/close works before a project is created.

## Current reference TIFF workflow

- [ ] Create a project in a user-chosen visible folder.
- [ ] Import the supplied `test.tif` and confirm 62 Z planes, 1024 × 234 pixels, one grayscale
      channel, 16-bit storage, and 0.446 µm Z spacing are displayed.
- [ ] Confirm the original TIFF remains byte-identical after import (compare SHA-256).
- [ ] Move through Z planes and verify raw display, mask overlay, ROI/geometry controls, and
      brightness controls remain responsive.
- [ ] Run the candidate deterministic analysis and confirm progress, cancel, and a successful
      completion path.
- [ ] Confirm per-plane plug area and corrected integrated intensity are present; review all
      other implemented metrics and QC/availability reasons.
- [ ] Save an immutable analysis run, close the app, reopen the project, and confirm the same
      saved values and provenance return.
- [ ] Export results and confirm CSV/JSON output opens independently of the application.
- [ ] Type a manual SME reference value, compare it with the estimate, and confirm leaving it
      blank remains valid.

## Failure and storage behavior

- [ ] Cancel an analysis and confirm no partial result is presented as a completed saved run.
- [ ] Attempt an import with deliberately insufficient free-space allowance and confirm it stops
      before processing with a clear, actionable message.
- [ ] Confirm Clear Cache states exactly what will be removed and preserves saved projects/runs.
- [ ] Confirm Delete Project requires the explicit project target and does not affect the source
      TIFF or another project.
- [ ] Confirm logs/settings/cache paths are visible in the UI and can be opened or reset using
      documented actions.

## Uninstall and record

- [ ] Uninstall the application through the normal platform mechanism.
- [ ] Confirm the executable is removed while user-created project folders remain intact.
- [ ] Record whether application settings/cache remain and verify the documented manual cleanup
      action removes only those paths.
- [ ] Record Pass/Fail/Blocked for every item, attach screenshots/logs for failures, and do not
      approve the release while a required item is untested.

Large-file acceptance (2–6 GB, low-resource, forced-stop, disk-full, and recovery testing) cannot
be completed with `test.tif`; run and record those gates once the genuine SME files and reference
Windows hardware are available.
