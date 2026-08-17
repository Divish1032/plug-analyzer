from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"
PACKAGING = PROJECT_ROOT / "packaging"
with (PROJECT_ROOT / "pyproject.toml").open("rb") as _pyproject_stream:
    APP_VERSION = str(tomllib.load(_pyproject_stream)["project"]["version"])


def test_macos_build_script_is_native_standalone_and_safely_scoped() -> None:
    script_path = SCRIPTS / "build_macos_arm64.sh"
    script = script_path.read_text(encoding="utf-8")

    subprocess.run(["bash", "-n", str(script_path)], check=True)
    assert '"$(uname -s)" == "Darwin"' in script
    assert '"$(uname -m)" == "arm64"' in script
    assert "--standalone" in script
    assert "--disable-cache=ccache" in script
    assert "--report=$BUILD_DIR/nuitka-compilation-report.xml" in script
    assert "--macos-create-app-bundle" in script
    assert 'MACOS_BUNDLE_IDENTIFIER="com.pluganalyzer.prototype"' in script
    assert "--macos-signed-app-name=$MACOS_BUNDLE_IDENTIFIER" in script
    assert "--enable-plugin=dill-compat" in script
    assert "--nofollow-import-to=*.tests" in script
    assert "--noinclude-pytest-mode=nofollow" in script
    assert "--include-package=dask.array" in script
    assert "--include-distribution-metadata=numpy" in script
    assert "--include-package=scipy._external.array_api_compat.numpy" in script
    assert "--include-package=scipy._external.array_api_compat\n" not in script
    assert "--include-module=PySide6.QtOpenGL" in script
    assert "--include-module=PySide6.QtOpenGLWidgets" in script
    assert "--include-module=PySide6.QtSvg" in script
    assert "--include-package=dask\n" not in script
    assert "--include-package=dask_image" not in script
    assert "--onefile" not in script
    assert "hdiutil create" in script
    assert "render_app_icon.py" in script
    assert "--macos-app-icon=$ICON_PNG" in script
    assert "lipo -archs" in script
    assert "CFBundleVersion" in script
    assert "LSMinimumSystemVersion" in script
    assert 'codesign --force --deep --sign - "$APP_BUNDLE"' in script
    assert "--platform macos-arm64" in script
    assert 'NUITKA_CACHE_DIR="$BUILD_DIR/nuitka-cache"' in script
    assert "--write-build-info" in script
    assert script.index("--write-build-info") < script.index("hdiutil create")
    assert 'cp "$RELEASE_DIR/BUILD_INFO.json" "$DMG_STAGE/"' in script
    assert 'case "$target" in' in script
    assert '[[ "$CLEAN" -eq 1 ]]' in script
    assert "uv.lock" in script
    assert "project version contains unsafe path characters" in script
    assert "QT_QPA_PLATFORM=offscreen" in script
    assert '"$APP_EXECUTABLE" "${BUNDLE_SMOKE_ARGS[@]}"' in script
    assert script.index('"$APP_EXECUTABLE" "${BUNDLE_SMOKE_ARGS[@]}"') < script.index(
        "hdiutil create"
    )
    assert '"$MOUNTED_EXECUTABLE" "${BUNDLE_SMOKE_ARGS[@]}"' in script


def test_windows_build_and_inno_definition_are_x64_standalone() -> None:
    script = (SCRIPTS / "build_windows_x64.ps1").read_text(encoding="utf-8")
    installer = (PACKAGING / "windows" / "PlugAnalyzer.iss").read_text(encoding="utf-8")

    assert "PlatformID]::Win32NT" in script
    assert "Is64BitOperatingSystem" in script
    assert "Is64BitProcess" in script
    assert '$env:PROCESSOR_ARCHITECTURE -ne "AMD64"' in script
    assert '"--standalone"' in script
    assert '"--assume-yes-for-downloads"' in script
    assert '"--report=$(Join-Path $BuildDir' in script
    assert '"--enable-plugin=dill-compat"' in script
    assert '"--nofollow-import-to=*.tests"' in script
    assert '"--noinclude-pytest-mode=nofollow"' in script
    assert '"--include-package=dask.array"' in script
    assert '"--include-distribution-metadata=numpy"' in script
    assert '"--include-package=scipy._external.array_api_compat.numpy"' in script
    assert '"--include-package=scipy._external.array_api_compat"' not in script
    assert '"--include-module=PySide6.QtOpenGL"' in script
    assert '"--include-module=PySide6.QtOpenGLWidgets"' in script
    assert '"--include-module=PySide6.QtSvg"' in script
    assert '"--include-package=dask"' not in script
    assert '"--include-package=dask_image"' not in script
    assert "--onefile" not in script
    assert "Inno Setup 6" in script
    assert "ISCC.exe" in script
    assert "render_app_icon.py" in script
    assert "--windows-icon-from-ico=$IconIco" in script
    assert "--platform windows-x64" in script
    assert '$env:NUITKA_CACHE_DIR = Join-Path $BuildDir "nuitka-cache"' in script
    assert "--write-build-info" in script
    assert script.index("--write-build-info") < script.index("& $Iscc")
    assert 'Join-Path $ReleaseDir "BUILD_INFO.json"' in script
    assert "Remove-Item -LiteralPath $FullTarget" in script
    assert "StartsWith($BuildPrefix" in script
    assert "StartsWith($DistPrefix" in script
    assert "$Machine -ne 0x8664" in script
    assert '$env:QT_QPA_PLATFORM = "offscreen"' in script
    assert "& $PackagedExe @SmokeArguments" in script
    assert script.index("& $PackagedExe @SmokeArguments") < script.index("& $Iscc")

    assert "AppId={{8D7E7D65-673C-4FF7-A929-3DB083F49A9D}" in installer
    assert "PrivilegesRequired=lowest" in installer
    assert "ArchitecturesAllowed=x64os" in installer
    assert "ArchitecturesInstallIn64BitMode=x64os" in installer
    assert "recursesubdirs createallsubdirs" in installer
    assert "windows-x64-Setup" in installer
    assert "SetupIconFile={#SetupIcon}" in installer


def test_makefile_keeps_build_and_deployment_separate() -> None:
    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")
    mac_deploy = (SCRIPTS / "deploy_macos_arm64.sh").read_text(encoding="utf-8")
    windows_deploy = (SCRIPTS / "deploy_windows_x64.ps1").read_text(encoding="utf-8")

    subprocess.run(["bash", "-n", str(SCRIPTS / "deploy_macos_arm64.sh")], check=True)
    assert ".DEFAULT_GOAL := help" in makefile
    assert "build: dependencies" not in makefile
    assert "build_macos_arm64.sh --clean" in makefile
    assert "deploy_macos_arm64.sh" in makefile
    assert 'build_windows_x64.ps1" -Clean' in makefile
    assert "deploy_windows_x64.ps1" in makefile
    assert "The Makefile never changes the application version." in makefile
    assert "pyproject.toml" in mac_deploy
    assert "verify_release.py" in mac_deploy
    assert "--bundle-smoke" in mac_deploy
    assert "Plug Analyzer is running; quit it before deployment" in mac_deploy
    assert "pyproject.toml" in windows_deploy
    assert "verify_release.py" in windows_deploy
    assert "Start-Process -FilePath $Installer" in windows_deploy
    assert "--bundle-smoke" in windows_deploy


def test_code_generated_icon_has_png_and_ico_signatures(tmp_path: Path) -> None:
    png_path = tmp_path / "PlugAnalyzer.png"
    ico_path = tmp_path / "PlugAnalyzer.ico"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "render_app_icon.py"),
            "--png",
            str(png_path),
            "--ico",
            str(ico_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert png_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert ico_path.read_bytes().startswith(b"\x00\x00\x01\x00\x01\x00")


def test_packaging_dependency_smoke_runs_from_source() -> None:
    entrypoint = (SCRIPTS / "gui_entrypoint.py").read_text(encoding="utf-8")
    assert 'distribution_version("numpy") == np.__version__' in entrypoint

    environment = dict(os.environ)
    environment["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "gui_entrypoint.py"), "--bundle-smoke"],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("bundle smoke: ok")


def test_release_support_policy_is_explicit() -> None:
    packaging_readme = (PACKAGING / "README.md").read_text(encoding="utf-8")
    checklist = (PACKAGING / "CLEAN_MACHINE_SMOKE_CHECKLIST.md").read_text(encoding="utf-8")
    notice_policy = (PACKAGING / "THIRD_PARTY_NOTICES_POLICY.md").read_text(encoding="utf-8")

    for filename in (
        "THIRD_PARTY_NOTICES.md",
        "CLEAN_MACHINE_SMOKE_CHECKLIST.md",
        "BUILD_INFO.json",
        "SHA256SUMS.txt",
        "release-manifest.json",
    ):
        assert filename in packaging_readme
    assert "test.tif" in checklist
    assert "62 Z planes" in checklist
    assert "byte-identical" in checklist
    assert "2\u20136 GB" in checklist
    assert "cannot" in checklist
    assert "committed `uv.lock`" in notice_policy
    assert "not legal advice" in notice_policy


def _run_verifier(artifacts_dir: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "verify_release.py"),
            "--project-root",
            str(PROJECT_ROOT),
            "--artifacts-dir",
            str(artifacts_dir),
            "--platform",
            "macos-arm64",
            *extra,
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_release_verifier_round_trip_and_corruption_detection(tmp_path: Path) -> None:
    artifact_name = f"Plug-Analyzer-{APP_VERSION}-macos-arm64.dmg"
    (tmp_path / artifact_name).write_bytes(b"synthetic test artifact")
    (tmp_path / "THIRD_PARTY_NOTICES.md").write_text("notices\n", encoding="utf-8")
    (tmp_path / "CLEAN_MACHINE_SMOKE_CHECKLIST.md").write_text("checklist\n", encoding="utf-8")

    build_info_created = _run_verifier(
        tmp_path,
        "--write-build-info",
        "--algorithm-version",
        APP_VERSION,
        "--protocol-version",
        "candidate-v1-unlocked",
    )
    assert build_info_created.returncode == 0, build_info_created.stderr
    embedded_build_info = (tmp_path / "BUILD_INFO.json").read_bytes()

    created = _run_verifier(
        tmp_path,
        "--write-manifest",
        "--algorithm-version",
        APP_VERSION,
        "--protocol-version",
        "candidate-v1-unlocked",
    )
    assert created.returncode == 0, created.stderr
    assert (tmp_path / "BUILD_INFO.json").read_bytes() == embedded_build_info

    manifest = json.loads((tmp_path / "release-manifest.json").read_text(encoding="utf-8"))
    assert manifest["app_version"] == APP_VERSION
    assert manifest["algorithm_version"] == APP_VERSION
    assert manifest["protocol_version"] == "candidate-v1-unlocked"
    assert manifest["target_platform"] == "macos-arm64"
    assert manifest["artifact"]["filename"] == artifact_name
    assert len(manifest["artifact"]["sha256"]) == 64
    build_info = json.loads((tmp_path / "BUILD_INFO.json").read_text(encoding="utf-8"))
    assert len(build_info["dependency_lock_sha256"]) == 64

    verified = _run_verifier(tmp_path)
    assert verified.returncode == 0, verified.stderr

    with (tmp_path / artifact_name).open("ab") as stream:
        stream.write(b"corruption")
    rejected = _run_verifier(tmp_path)
    assert rejected.returncode == 2
    assert "checksum mismatch" in rejected.stderr


def test_release_verifier_rejects_wrong_project_version(tmp_path: Path) -> None:
    wrong_name = "Plug-Analyzer-9.9.9-macos-arm64.dmg"
    (tmp_path / wrong_name).write_bytes(b"artifact")
    (tmp_path / "THIRD_PARTY_NOTICES.md").write_text("notices\n", encoding="utf-8")
    (tmp_path / "CLEAN_MACHINE_SMOKE_CHECKLIST.md").write_text("checklist\n", encoding="utf-8")

    result = _run_verifier(tmp_path, "--write-manifest", "--version", "9.9.9")
    assert result.returncode == 2
    assert "does not match pyproject version" in result.stderr
