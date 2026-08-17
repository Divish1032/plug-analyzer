# Plug Analyzer developer commands. Run `make help` first.

.DEFAULT_GOAL := help

PROTOCOL_VERSION ?= candidate-v1-unlocked
ALGORITHM_VERSION ?=
INSTALL_DIR ?= /Applications
POWERSHELL ?= powershell.exe

ifeq ($(OS),Windows_NT)
PYTHON := .venv/Scripts/python.exe
NATIVE_BUILD_TARGET := build-windows
NATIVE_DEPLOY_TARGET := deploy-windows
NATIVE_VERIFY_TARGET := verify-windows
NATIVE_ARTIFACT_TARGET := artifact-windows
else
PYTHON := .venv/bin/python
UNAME_S := $(shell uname -s 2>/dev/null)
ifeq ($(UNAME_S),Darwin)
NATIVE_BUILD_TARGET := build-mac
NATIVE_DEPLOY_TARGET := deploy-mac
NATIVE_VERIFY_TARGET := verify-mac
NATIVE_ARTIFACT_TARGET := artifact-mac
else
NATIVE_BUILD_TARGET := unsupported-platform
NATIVE_DEPLOY_TARGET := unsupported-platform
NATIVE_VERIFY_TARGET := unsupported-platform
NATIVE_ARTIFACT_TARGET := unsupported-platform
endif
endif

ALGORITHM_MAC_ARG = $(if $(strip $(ALGORITHM_VERSION)),--algorithm-version "$(ALGORITHM_VERSION)",)
ALGORITHM_WINDOWS_ARG = $(if $(strip $(ALGORITHM_VERSION)),-AlgorithmVersion "$(ALGORITHM_VERSION)",)

.PHONY: help setup check test build deploy verify artifact \
	build-mac deploy-mac verify-mac artifact-mac \
	build-windows deploy-windows verify-windows artifact-windows \
	unsupported-platform

help:
	@echo "Plug Analyzer commands"
	@echo ""
	@echo "  make setup           Install locked development/build dependencies"
	@echo "  make check           Run formatter check, lint, and all tests"
	@echo "  make build           Build a fresh installer for this native OS"
	@echo "  make deploy          Install the existing installer; never rebuilds"
	@echo "  make verify          Verify the existing native release and checksums"
	@echo "  make artifact        Print the existing native installer path"
	@echo ""
	@echo "Explicit native targets:"
	@echo "  make build-mac       Apple Silicon macOS only"
	@echo "  make deploy-mac      Install into /Applications by default"
	@echo "  make build-windows   Native Windows x64 only"
	@echo "  make deploy-windows  Run and verify the per-user Windows installer"
	@echo ""
	@echo "Optional build variables:"
	@echo "  PROTOCOL_VERSION=<label>   Default: candidate-v1-unlocked"
	@echo "  ALGORITHM_VERSION=<label>  Default: app version from pyproject.toml"
	@echo "  INSTALL_DIR=<path>         macOS deploy destination; default: /Applications"
	@echo ""
	@echo "The Makefile never changes the application version."

setup:
	uv sync --frozen --extra dev --extra packaging

test:
	@test -x "$(PYTHON)" || { echo "Missing $(PYTHON); run: make setup" >&2; exit 2; }
	QT_QPA_PLATFORM=offscreen "$(PYTHON)" -m pytest -q

check:
	@test -x "$(PYTHON)" || { echo "Missing $(PYTHON); run: make setup" >&2; exit 2; }
	"$(PYTHON)" -m ruff format --check src tests scripts
	"$(PYTHON)" -m ruff check src tests scripts
	QT_QPA_PLATFORM=offscreen "$(PYTHON)" -m pytest -q

build:
	@$(MAKE) --no-print-directory $(NATIVE_BUILD_TARGET)

deploy:
	@$(MAKE) --no-print-directory $(NATIVE_DEPLOY_TARGET)

verify:
	@$(MAKE) --no-print-directory $(NATIVE_VERIFY_TARGET)

artifact:
	@$(MAKE) --no-print-directory $(NATIVE_ARTIFACT_TARGET)

build-mac:
	./scripts/build_macos_arm64.sh --clean \
		--protocol-version "$(PROTOCOL_VERSION)" $(ALGORITHM_MAC_ARG)

deploy-mac:
	PLUG_ANALYZER_INSTALL_DIR="$(INSTALL_DIR)" ./scripts/deploy_macos_arm64.sh

verify-mac:
	@test -x ".venv/bin/python" || { echo "Missing .venv; run: make setup" >&2; exit 2; }
	@VERSION="$$(.venv/bin/python -c 'import pathlib,tomllib; print(tomllib.loads(pathlib.Path("pyproject.toml").read_text())["project"]["version"])')"; \
	.venv/bin/python scripts/verify_release.py \
		--artifacts-dir "dist/release/$$VERSION/macos-arm64" \
		--platform macos-arm64 --version "$$VERSION" --deep

artifact-mac:
	@test -x ".venv/bin/python" || { echo "Missing .venv; run: make setup" >&2; exit 2; }
	@VERSION="$$(.venv/bin/python -c 'import pathlib,tomllib; print(tomllib.loads(pathlib.Path("pyproject.toml").read_text())["project"]["version"])')"; \
	ARTIFACT="dist/release/$$VERSION/macos-arm64/Plug-Analyzer-$$VERSION-macos-arm64.dmg"; \
	test -f "$$ARTIFACT" || { echo "Missing $$ARTIFACT; run: make build-mac" >&2; exit 2; }; \
	echo "$$ARTIFACT"

build-windows:
	$(POWERSHELL) -NoProfile -File "scripts/build_windows_x64.ps1" -Clean \
		-ProtocolVersion "$(PROTOCOL_VERSION)" $(ALGORITHM_WINDOWS_ARG)

deploy-windows:
	$(POWERSHELL) -NoProfile -File "scripts/deploy_windows_x64.ps1"

verify-windows:
	$(POWERSHELL) -NoProfile -File "scripts/deploy_windows_x64.ps1" -VerifyOnly

artifact-windows:
	$(POWERSHELL) -NoProfile -File "scripts/deploy_windows_x64.ps1" -PrintArtifact

unsupported-platform:
	@echo "Plug Analyzer release commands require Apple Silicon macOS or native Windows x64." >&2
	@exit 2
