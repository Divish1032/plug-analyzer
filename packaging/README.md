# Packaging and internal release

Plug Analyzer is packaged as a Nuitka **standalone** application. It does not use Nuitka
onefile extraction. The recipient still gets one installer: a DMG for Apple Silicon macOS or
an Inno Setup `Setup.exe` for Windows x64.

## Release directory contract

Each platform release directory contains exactly the following tracked deliverables:

```text
Plug-Analyzer-<version>-<platform>.<installer suffix>
THIRD_PARTY_NOTICES.md
CLEAN_MACHINE_SMOKE_CHECKLIST.md
BUILD_INFO.json
SHA256SUMS.txt
release-manifest.json
```

`BUILD_INFO.json` records app, algorithm, and scientific-protocol versions plus the exact
dependency-lock SHA-256. The manifest and
checksum file cover the installer, build information, notices, and checklist. The manifest is
not self-hashed, because changing its own hash would be circular.

## Release sequence

1. Confirm `uv.lock` represents the approved source and run the full test suite.
2. Build macOS on Apple Silicon macOS and Windows on Windows x64; do not cross-build.
3. Preserve the generated release directory without editing checksummed files.
4. Transfer the installer together with `SHA256SUMS.txt` through the agreed internal channel.
5. Verify the hash after transfer, then execute every applicable clean-machine smoke check.
6. Record the test machine, result, failures, and operator in the release record.

The current internal pilot is unsigned. This is independent of App Store publication. Gatekeeper
and SmartScreen can warn about unsigned artifacts; the platform read-first files describe the
normal visible UI path. Do not tell users to disable operating-system security controls.

## Deferred release work

- Apple Developer ID signing and notarization.
- Windows Authenticode signing.
- Intel or universal macOS builds.
- Automatic updates.
- Public distribution.

These are explicitly outside the prototype target and must not be inferred from the presence of
the build scaffolding.
