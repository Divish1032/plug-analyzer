# Read first — Apple Silicon macOS internal pilot

This internal prototype is unsigned and not notarized. Confirm the DMG SHA-256 against the supplied
`SHA256SUMS.txt` before opening it. Drag **Plug Analyzer** to the Applications shortcut.

macOS may block the first launch because the developer cannot be verified. If your organization
permits this internal build, use Finder to Control-click the app, choose **Open**, then confirm
**Open**. On some macOS versions the corresponding approval appears in **System Settings → Privacy
& Security** after a blocked launch. Do not disable Gatekeeper globally and do not run commands that
remove quarantine/security attributes.

Projects are user-chosen visible folders and are not removed when the app is deleted. The clean
machine checklist must be completed before the build is passed to an SME.
