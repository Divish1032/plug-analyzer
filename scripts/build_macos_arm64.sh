#!/usr/bin/env bash
# Build the unsigned internal Apple Silicon application bundle and DMG.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
PYTHON="$PROJECT_ROOT/.venv/bin/python"
ENTRYPOINT="$SCRIPT_DIR/gui_entrypoint.py"
CLEAN=0
SKIP_TESTS=0
PROTOCOL_VERSION="candidate-v1-unlocked"
ALGORITHM_VERSION=""
MACOS_BUNDLE_IDENTIFIER="com.pluganalyzer.prototype"

usage() {
    cat <<'EOF'
Usage: scripts/build_macos_arm64.sh [options]

Options:
  --clean                       Replace this version's existing build/output folders.
  --skip-tests                  Skip pytest (intended only after tests ran separately).
  --protocol-version VALUE      Recorded scientific protocol version.
  --algorithm-version VALUE     Recorded algorithm version (defaults to app version).
  -h, --help                    Show this help.
EOF
}

fail() {
    printf 'macOS release build failed: %s\n' "$*" >&2
    exit 2
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --clean)
            CLEAN=1
            shift
            ;;
        --skip-tests)
            SKIP_TESTS=1
            shift
            ;;
        --protocol-version)
            [[ $# -ge 2 && -n "$2" ]] || fail "--protocol-version needs a value"
            PROTOCOL_VERSION="$2"
            shift 2
            ;;
        --algorithm-version)
            [[ $# -ge 2 && -n "$2" ]] || fail "--algorithm-version needs a value"
            ALGORITHM_VERSION="$2"
            shift 2
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
[[ "$(uname -m)" == "arm64" ]] || fail "this target must be built on Apple Silicon (arm64)"
[[ -x "$PYTHON" ]] || fail "missing $PYTHON; run: uv sync --frozen --extra dev --extra packaging"
[[ -f "$PROJECT_ROOT/uv.lock" ]] || fail "uv.lock is required for a reproducible build"
[[ -f "$ENTRYPOINT" ]] || fail "missing packaging entry point: $ENTRYPOINT"
[[ -f "$PROJECT_ROOT/src/plug_analyzer/app.py" ]] || fail "GUI entry point is not implemented yet"
command -v hdiutil >/dev/null 2>&1 || fail "hdiutil is required"
command -v ditto >/dev/null 2>&1 || fail "ditto is required"
command -v lipo >/dev/null 2>&1 || fail "lipo is required"
command -v codesign >/dev/null 2>&1 || fail "codesign is required"
command -v xcrun >/dev/null 2>&1 || fail "Xcode Command Line Tools are required"
xcrun --find clang >/dev/null 2>&1 || fail "clang was not found; install Xcode Command Line Tools"

"$PYTHON" -c 'import nuitka' >/dev/null 2>&1 || \
    fail "Nuitka is missing; run: uv sync --frozen --extra dev --extra packaging"
[[ "$("$PYTHON" -c 'import platform; print(platform.machine())')" == "arm64" ]] || \
    fail "the project .venv Python is not arm64"

VERSION="$("$PYTHON" -c 'import pathlib,sys,tomllib; print(tomllib.loads(pathlib.Path(sys.argv[1]).read_text())["project"]["version"])' "$PROJECT_ROOT/pyproject.toml" 2>/dev/null)" || \
    fail "could not read the version from pyproject.toml"
[[ -n "$VERSION" ]] || fail "project version is empty"
[[ "$VERSION" =~ ^[0-9A-Za-z][0-9A-Za-z._-]*$ ]] || \
    fail "project version contains unsafe path characters: $VERSION"
[[ -n "$ALGORITHM_VERSION" ]] || ALGORITHM_VERSION="$VERSION"

BUILD_PARENT="$PROJECT_ROOT/build/release"
DIST_PARENT="$PROJECT_ROOT/dist/release"
BUILD_DIR="$BUILD_PARENT/$VERSION/macos-arm64"
RELEASE_DIR="$DIST_PARENT/$VERSION/macos-arm64"
NUITKA_OUTPUT="$BUILD_DIR/nuitka"
DMG_STAGE="$BUILD_DIR/dmg-root"
ICON_PNG="$BUILD_DIR/PlugAnalyzer.png"
ICON_ICO="$BUILD_DIR/PlugAnalyzer.ico"
DMG_NAME="Plug-Analyzer-$VERSION-macos-arm64.dmg"
DMG_PATH="$RELEASE_DIR/$DMG_NAME"

prepare_dir() {
    local target="$1"
    case "$target" in
        "$BUILD_PARENT"/*|"$DIST_PARENT"/*) ;;
        *) fail "refusing to modify a path outside the versioned release roots: $target" ;;
    esac
    [[ "$target" != "$BUILD_PARENT" && "$target" != "$DIST_PARENT" ]] || \
        fail "refusing to modify a release root"
    if [[ -e "$target" ]]; then
        [[ "$CLEAN" -eq 1 ]] || fail "$target already exists; rerun with --clean to replace it"
        rm -rf -- "$target"
    fi
    mkdir -p "$target"
}

cd "$PROJECT_ROOT"
prepare_dir "$BUILD_DIR"
prepare_dir "$RELEASE_DIR"

if [[ "$SKIP_TESTS" -eq 0 ]]; then
    QT_QPA_PLATFORM=offscreen "$PYTHON" -m pytest
fi

"$PYTHON" "$SCRIPT_DIR/generate_third_party_notices.py" \
    --output "$RELEASE_DIR/THIRD_PARTY_NOTICES.md"
cp "$PROJECT_ROOT/packaging/CLEAN_MACHINE_SMOKE_CHECKLIST.md" "$RELEASE_DIR/"
"$PYTHON" "$SCRIPT_DIR/verify_release.py" \
    --artifacts-dir "$RELEASE_DIR" \
    --platform macos-arm64 \
    --version "$VERSION" \
    --algorithm-version "$ALGORITHM_VERSION" \
    --protocol-version "$PROTOCOL_VERSION" \
    --write-build-info
"$PYTHON" "$SCRIPT_DIR/render_app_icon.py" --png "$ICON_PNG" --ico "$ICON_ICO"

NUITKA_ARGS=(
    --standalone
    --disable-cache=ccache
    "--report=$BUILD_DIR/nuitka-compilation-report.xml"
    --enable-plugin=pyside6
    --enable-plugin=dill-compat
    '--nofollow-import-to=*.tests'
    --noinclude-pytest-mode=nofollow
    --macos-create-app-bundle
    "--macos-signed-app-name=$MACOS_BUNDLE_IDENTIFIER"
    "--macos-app-name=Plug Analyzer"
    "--macos-app-version=$VERSION"
    "--macos-app-icon=$ICON_PNG"
    "--output-dir=$NUITKA_OUTPUT"
    --output-filename=PlugAnalyzer
    --include-package=plug_analyzer
    --include-package-data=plug_analyzer
    --include-module=PySide6.QtOpenGL
    --include-module=PySide6.QtOpenGLWidgets
    --include-module=PySide6.QtSvg
    --include-package=pyqtgraph
    --include-package-data=pyqtgraph
    --include-package=tifffile
    --include-package=imagecodecs
    --include-package=nd2
    --include-package-data=nd2
    --include-package=zarr
    --include-package=dask.array
    --include-distribution-metadata=numpy
    --include-package=scipy._external.array_api_compat.numpy
    "$ENTRYPOINT"
)
NUITKA_CACHE_DIR="$BUILD_DIR/nuitka-cache" "$PYTHON" -m nuitka "${NUITKA_ARGS[@]}"

APP_BUNDLES=()
while IFS= read -r app_bundle; do
    APP_BUNDLES+=("$app_bundle")
done < <(find "$NUITKA_OUTPUT" -maxdepth 1 -type d -name '*.app' -print)
[[ "${#APP_BUNDLES[@]}" -eq 1 ]] || \
    fail "expected one .app in $NUITKA_OUTPUT; found ${#APP_BUNDLES[@]}"
APP_BUNDLE="${APP_BUNDLES[0]}"
INFO_PLIST="$APP_BUNDLE/Contents/Info.plist"
[[ -f "$INFO_PLIST" ]] || fail "app bundle has no Info.plist: $APP_BUNDLE"

set_plist_string() {
    local plist="$1"
    local key="$2"
    local value="$3"
    if /usr/libexec/PlistBuddy -c "Print :$key" "$plist" >/dev/null 2>&1; then
        /usr/libexec/PlistBuddy -c "Set :$key $value" "$plist"
    else
        /usr/libexec/PlistBuddy -c "Add :$key string $value" "$plist"
    fi
}

set_plist_string "$INFO_PLIST" CFBundleVersion "$VERSION"
set_plist_string "$INFO_PLIST" LSMinimumSystemVersion "11.0"
codesign --force --deep --sign - "$APP_BUNDLE"
codesign --verify --deep --strict "$APP_BUNDLE" || fail "app bundle signature is invalid"

BUNDLE_IDENTIFIER="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$INFO_PLIST")" || \
    fail "cannot identify the app bundle identifier"
[[ "$BUNDLE_IDENTIFIER" == "$MACOS_BUNDLE_IDENTIFIER" ]] || \
    fail "unexpected app bundle identifier: $BUNDLE_IDENTIFIER"
APP_EXECUTABLE_NAME="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$INFO_PLIST")" || \
    fail "cannot identify the app executable"
APP_EXECUTABLE="$APP_BUNDLE/Contents/MacOS/$APP_EXECUTABLE_NAME"
[[ -x "$APP_EXECUTABLE" ]] || fail "app executable is missing: $APP_EXECUTABLE"
ARCHITECTURES="$(lipo -archs "$APP_EXECUTABLE")" || fail "cannot inspect app architecture"
[[ " $ARCHITECTURES " == *" arm64 "* ]] || \
    fail "app executable is not arm64 (reported: $ARCHITECTURES)"

BUNDLE_SMOKE_ARGS=(--bundle-smoke)
REGRESSION_TIFF="$PROJECT_ROOT/../test.tif"
if [[ -f "$REGRESSION_TIFF" ]]; then
    BUNDLE_SMOKE_ARGS+=("$REGRESSION_TIFF")
fi
QT_QPA_PLATFORM=offscreen "$APP_EXECUTABLE" "${BUNDLE_SMOKE_ARGS[@]}" || \
    fail "packaged application dependency smoke failed"

mkdir -p "$DMG_STAGE"
ditto "$APP_BUNDLE" "$DMG_STAGE/Plug Analyzer.app"
cp "$RELEASE_DIR/THIRD_PARTY_NOTICES.md" "$DMG_STAGE/"
cp "$RELEASE_DIR/BUILD_INFO.json" "$DMG_STAGE/"
cp "$RELEASE_DIR/CLEAN_MACHINE_SMOKE_CHECKLIST.md" "$DMG_STAGE/"
cp "$PROJECT_ROOT/packaging/macos/PILOT_INSTALL.md" "$DMG_STAGE/READ_ME_FIRST.md"
ln -s /Applications "$DMG_STAGE/Applications"

hdiutil create \
    -volname "Plug Analyzer $VERSION" \
    -srcfolder "$DMG_STAGE" \
    -ov \
    -format UDZO \
    "$DMG_PATH"

MOUNT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/plug-analyzer-dmg-smoke.XXXXXX")" || \
    fail "could not create a temporary DMG mount directory"
MOUNT_ATTACHED=0
cleanup_mount() {
    set +e
    if [[ "$MOUNT_ATTACHED" -eq 1 ]]; then
        hdiutil detach "$MOUNT_DIR" >/dev/null
    fi
    rmdir "$MOUNT_DIR" >/dev/null 2>&1
}
trap cleanup_mount EXIT
hdiutil attach "$DMG_PATH" -readonly -nobrowse -mountpoint "$MOUNT_DIR" >/dev/null || \
    fail "could not mount the completed DMG read-only"
MOUNT_ATTACHED=1
MOUNTED_EXECUTABLE="$MOUNT_DIR/Plug Analyzer.app/Contents/MacOS/$APP_EXECUTABLE_NAME"
[[ -x "$MOUNTED_EXECUTABLE" ]] || fail "mounted DMG has no packaged executable"
QT_QPA_PLATFORM=offscreen "$MOUNTED_EXECUTABLE" "${BUNDLE_SMOKE_ARGS[@]}" || \
    fail "mounted DMG application dependency smoke failed"
hdiutil detach "$MOUNT_DIR" >/dev/null || fail "could not detach the verified DMG"
MOUNT_ATTACHED=0
rmdir "$MOUNT_DIR" || fail "could not remove the temporary DMG mount directory"
trap - EXIT

"$PYTHON" "$SCRIPT_DIR/verify_release.py" \
    --artifacts-dir "$RELEASE_DIR" \
    --platform macos-arm64 \
    --version "$VERSION" \
    --algorithm-version "$ALGORITHM_VERSION" \
    --protocol-version "$PROTOCOL_VERSION" \
    --write-manifest \
    --deep

printf 'Unsigned internal macOS release created: %s\n' "$DMG_PATH"
printf 'Verify SHA-256 values in: %s\n' "$RELEASE_DIR/SHA256SUMS.txt"
