# Development and release scripts

These entry points are for developers and release operators. End users receive only the
platform installer and the support files beside it.

## Simple Make commands

From the repository root, run `make help`. The normal local workflow is:

```text
make setup
make check
make build
make deploy
```

`build` selects Apple Silicon macOS or Windows x64 from the current machine and creates a fresh
installer. `deploy` is deliberately separate: it verifies and installs the already-built native
installer and never starts a build. Explicit equivalents are `build-mac`, `deploy-mac`,
`build-windows`, and `deploy-windows`. `make verify` checks an existing release without installing
it, while `make artifact` prints its installer path.

The Makefile reads the application version from `pyproject.toml`; none of its targets changes the
version. Windows requires GNU Make plus native 64-bit PowerShell. The PowerShell scripts remain
directly callable when GNU Make is unavailable.

## Build prerequisites

Create the project-local environment from the committed lock file:

```text
uv sync --frozen --extra dev --extra packaging
```

The build scripts deliberately do not install or update packages. They fail if `.venv`,
Nuitka, the lock file, the GUI entry point, or a native packaging tool is absent.

## Apple Silicon macOS

Run on an Apple Silicon Mac with Xcode Command Line Tools installed:

```text
./scripts/build_macos_arm64.sh --protocol-version candidate-v1-unlocked
```

Use `--clean` only when intentionally replacing the build and output folders for the same
version. Output is written below `dist/release/<version>/macos-arm64/`. The script produces
an unsigned `.app`, verifies its arm64 executable, creates a compressed DMG with `hdiutil`,
and creates/verifies release checksums and metadata.

## Windows x64

Run from 64-bit PowerShell on a Windows x64 machine with a Nuitka-supported C compiler and
Inno Setup 6.3 or newer installed. Visual Studio 2022 Build Tools are recommended. Nuitka may
download its pinned dependency-inspection support tools into the version-scoped build cache;
the packaged application itself never downloads or depends on them.

```text
.\scripts\build_windows_x64.ps1 -ProtocolVersion candidate-v1-unlocked
```

Output is written below `dist\release\<version>\windows-x64\`. Windows must be built on
Windows; the script refuses macOS/Linux execution. No Windows artifact is produced or
validated by running the macOS script.

## Supporting tools

- `generate_third_party_notices.py` walks the installed runtime dependency closure and
  embeds license texts exposed by wheel metadata.
- `verify_release.py` checks app/platform/version consistency, file presence, exact sizes,
  SHA-256 hashes, and the release manifest. Build scripts use `--write-build-info` before
  packaging so provenance is embedded, then `--write-manifest` after the installer exists;
  verification without either flag never rewrites the recorded hashes.
- `gui_entrypoint.py` is the stable source program passed to Nuitka.
- `render_app_icon.py` draws the channel/plug icon in code and emits platform build assets;
  no untraceable binary artwork is committed.

The default protocol label is deliberately `candidate-v1-unlocked`. A release must never be
renamed to “validated” until the scientific lock and SME approval recorded in the plan exist.
