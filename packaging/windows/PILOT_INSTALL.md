# Read first — Windows x64 internal pilot

This internal prototype is not Authenticode signed. Confirm the installer SHA-256 against the
supplied `SHA256SUMS.txt` before running it. Windows SmartScreen may show an unrecognized-app warning.
Proceed through **More info → Run anyway** only when your organization permits the internal build
and the checksum matches. Do not disable SmartScreen or antivirus protection.

The installer is per-user and does not require a Python installation. Projects are user-chosen
visible folders and are not removed by uninstalling the app. The clean-machine checklist must be
completed on the actual SME Windows hardware before release approval.
