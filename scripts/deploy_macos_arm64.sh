#!/usr/bin/env bash
# Verify and locally install an already-built Apple Silicon DMG.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
PYTHON="$PROJECT_ROOT/.venv/bin/python"
INSTALL_DIR="${PLUG_ANALYZER_INSTALL_DIR:-/Applications}"
LAUNCH=0

usage() {
    cat <<'EOF'
Usage: scripts/deploy_macos_arm64.sh [--launch]

Verifies and installs the existing DMG for the version declared in pyproject.toml.
It never builds the application and never edits the version.

Environment:
  PLUG_ANALYZER_INSTALL_DIR   Destination directory (default: /Applications)
EOF
}

fail() {
    printf 'macOS deployment failed: %s\n' "$*" >&2
    exit 2
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --launch)
            LAUNCH=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            fail "unknown argument: $1"
            ;;
    esac
done

[[ "$(uname -s)" == "Darwin" ]] || fail "this script must run on macOS"
[[ "$(uname -m)" == "arm64" ]] || fail "this deployment target requires Apple Silicon"
[[ -x "$PYTHON" ]] || fail "missing $PYTHON; run: make setup"
[[ "$INSTALL_DIR" == /* ]] || fail "PLUG_ANALYZER_INSTALL_DIR must be an absolute path"
[[ "$INSTALL_DIR" != "/" ]] || fail "refusing to use the filesystem root as INSTALL_DIR"
[[ -d "$INSTALL_DIR" ]] || fail "install directory does not exist: $INSTALL_DIR"
[[ -w "$INSTALL_DIR" ]] || fail "install directory is not writable: $INSTALL_DIR"
command -v hdiutil >/dev/null 2>&1 || fail "hdiutil is required"
command -v ditto >/dev/null 2>&1 || fail "ditto is required"
command -v codesign >/dev/null 2>&1 || fail "codesign is required"
command -v lipo >/dev/null 2>&1 || fail "lipo is required"

VERSION="$("$PYTHON" -c 'import pathlib,sys,tomllib; print(tomllib.loads(pathlib.Path(sys.argv[1]).read_text())["project"]["version"])' "$PROJECT_ROOT/pyproject.toml")" || \
    fail "could not read the application version"
[[ -n "$VERSION" ]] || fail "application version is empty"
RELEASE_DIR="$PROJECT_ROOT/dist/release/$VERSION/macos-arm64"
DMG_PATH="$RELEASE_DIR/Plug-Analyzer-$VERSION-macos-arm64.dmg"
[[ -f "$DMG_PATH" ]] || fail "missing $DMG_PATH; run: make build-mac"

cd "$PROJECT_ROOT"
"$PYTHON" "$SCRIPT_DIR/verify_release.py" \
    --artifacts-dir "$RELEASE_DIR" \
    --platform macos-arm64 \
    --version "$VERSION" \
    --deep

TARGET_APP="$INSTALL_DIR/Plug Analyzer.app"
TARGET_EXECUTABLE="$TARGET_APP/Contents/MacOS/PlugAnalyzer"
if pgrep -f "$TARGET_EXECUTABLE" >/dev/null 2>&1; then
    fail "Plug Analyzer is running; quit it before deployment"
fi

MOUNT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/plug-analyzer-deploy.XXXXXX")" || \
    fail "could not create a temporary mount directory"
MOUNT_ATTACHED=0
STAGED_APP="$INSTALL_DIR/.Plug Analyzer.app.install-$$"
BACKUP_APP="$INSTALL_DIR/.Plug Analyzer.app.backup-$$"
TARGET_REPLACED=0
TARGET_INSTALLED=0

cleanup() {
    local exit_code=$?
    set +e
    if [[ "$MOUNT_ATTACHED" -eq 1 ]]; then
        hdiutil detach "$MOUNT_DIR" >/dev/null
    fi
    rmdir "$MOUNT_DIR" >/dev/null 2>&1
    if [[ -e "$STAGED_APP" ]]; then
        rm -rf -- "$STAGED_APP"
    fi
    if [[ "$exit_code" -ne 0 ]]; then
        if [[ "$TARGET_INSTALLED" -eq 1 && -e "$TARGET_APP" ]]; then
            rm -rf -- "$TARGET_APP"
        fi
        if [[ "$TARGET_REPLACED" -eq 1 && -e "$BACKUP_APP" ]]; then
            mv "$BACKUP_APP" "$TARGET_APP"
        fi
    fi
    exit "$exit_code"
}
trap cleanup EXIT

[[ ! -e "$STAGED_APP" && ! -e "$BACKUP_APP" ]] || \
    fail "temporary deployment paths already exist; remove them and retry"
hdiutil attach "$DMG_PATH" -readonly -nobrowse -mountpoint "$MOUNT_DIR" >/dev/null || \
    fail "could not mount the release DMG"
MOUNT_ATTACHED=1
SOURCE_APP="$MOUNT_DIR/Plug Analyzer.app"
SOURCE_EXECUTABLE="$SOURCE_APP/Contents/MacOS/PlugAnalyzer"
[[ -x "$SOURCE_EXECUTABLE" ]] || fail "the mounted DMG has no Plug Analyzer executable"
[[ "$(lipo -archs "$SOURCE_EXECUTABLE")" == *arm64* ]] || fail "the DMG app is not arm64"
[[ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$SOURCE_APP/Contents/Info.plist")" == \
    "com.pluganalyzer.prototype" ]] || fail "the DMG app has an unexpected bundle identifier"
[[ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$SOURCE_APP/Contents/Info.plist")" == \
    "$VERSION" ]] || fail "the DMG app version does not match pyproject.toml"
codesign --verify --deep --strict "$SOURCE_APP" || fail "the DMG app signature is invalid"

ditto "$SOURCE_APP" "$STAGED_APP"
SMOKE_ARGS=(--bundle-smoke)
REGRESSION_TIFF="$PROJECT_ROOT/../test.tif"
if [[ -f "$REGRESSION_TIFF" ]]; then
    SMOKE_ARGS+=("$REGRESSION_TIFF")
fi
QT_QPA_PLATFORM=offscreen "$STAGED_APP/Contents/MacOS/PlugAnalyzer" "${SMOKE_ARGS[@]}" || \
    fail "the staged app failed its dependency smoke test"

if [[ -e "$TARGET_APP" ]]; then
    mv "$TARGET_APP" "$BACKUP_APP"
    TARGET_REPLACED=1
fi
if ! mv "$STAGED_APP" "$TARGET_APP"; then
    fail "could not place the app in $INSTALL_DIR"
fi
TARGET_INSTALLED=1
codesign --verify --deep --strict "$TARGET_APP" || fail "the installed app signature is invalid"
QT_QPA_PLATFORM=offscreen "$TARGET_EXECUTABLE" "${SMOKE_ARGS[@]}" || \
    fail "the installed app failed its dependency smoke test"

if [[ -e "$BACKUP_APP" ]]; then
    rm -rf -- "$BACKUP_APP"
fi
TARGET_REPLACED=0
TARGET_INSTALLED=0

LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
if [[ -x "$LSREGISTER" ]]; then
    "$LSREGISTER" -f "$TARGET_APP"
fi

hdiutil detach "$MOUNT_DIR" >/dev/null || fail "could not detach the release DMG"
MOUNT_ATTACHED=0
rmdir "$MOUNT_DIR" || fail "could not remove the temporary mount directory"
trap - EXIT

printf 'Installed Plug Analyzer %s at: %s\n' "$VERSION" "$TARGET_APP"
if [[ "$LAUNCH" -eq 1 ]]; then
    open "$TARGET_APP"
fi
