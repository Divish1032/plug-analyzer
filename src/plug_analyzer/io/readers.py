"""Content-based microscope reader detection and construction."""

from __future__ import annotations

from pathlib import Path

from .errors import UnsupportedFormatError
from .models import DatasetInfo, MicroscopeReader
from .nd2_reader import ND2Reader, is_nd2_content, nd2_compatibility_report
from .tiff import TiffReader, is_tiff_content


def open_reader(path: str | Path) -> MicroscopeReader:
    """Open by file contents; the filename extension is only diagnostic context."""

    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise UnsupportedFormatError(resolved, "The selected source is not a readable file.")
    if is_tiff_content(resolved):
        return TiffReader(resolved)
    if is_nd2_content(resolved):
        return ND2Reader(resolved)
    if resolved.suffix.lower() == ".nd2":
        reason = "The .nd2 extension is present, but the content is not a recognized ND2 container."
        raise UnsupportedFormatError(
            resolved,
            reason,
            compatibility_report=nd2_compatibility_report(resolved, reason),
        )
    raise UnsupportedFormatError(
        resolved,
        "Content is not a recognized TIFF, BigTIFF, OME-TIFF, ImageJ TIFF, or Nikon ND2 file.",
    )


def probe_source(path: str | Path) -> DatasetInfo:
    """Convenience content/metadata probe."""

    return open_reader(path).probe()
