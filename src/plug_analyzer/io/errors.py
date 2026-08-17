"""Explicit, user-facing failures for microscope input and cache operations."""

from __future__ import annotations

from pathlib import Path


class MicroscopeIOError(RuntimeError):
    """Base class for failures that can be presented without a traceback."""


class UnsupportedFormatError(MicroscopeIOError):
    """The source is not a supported TIFF or ND2 file."""

    def __init__(self, path: Path, reason: str, *, compatibility_report: str | None = None):
        self.path = Path(path)
        self.reason = reason
        self.compatibility_report = compatibility_report or reason
        super().__init__(f"Cannot open {self.path.name}: {reason}")


class SourceReadError(MicroscopeIOError):
    """A supported source is unreadable, truncated, or internally inconsistent."""


class SelectionError(MicroscopeIOError):
    """A requested scene, time, channel, or region is invalid or ambiguous."""


class CacheError(MicroscopeIOError):
    """A normalized cache cannot be created, resumed, or verified."""


class ImportCancelled(CacheError):
    """The caller requested cooperative cancellation between chunks."""

    def __init__(self, partial_path: Path | None = None):
        self.partial_path = Path(partial_path) if partial_path is not None else None
        detail = (
            f"; resumable work is in {self.partial_path}" if self.partial_path is not None else ""
        )
        super().__init__(f"Import cancelled{detail}")
