"""Shared bounded-iteration implementation for microscope readers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from ._util import chunk_slices, normalize_region, selection_bounds
from .errors import SelectionError
from .models import DatasetInfo, SceneInfo, VolumeChunk, VolumeSelection


class BaseMicroscopeReader(ABC):
    """Small adapter base that keeps selection and chunk semantics identical."""

    reader_id: str

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        if not self.path.is_file():
            raise SelectionError(f"Source file does not exist: {self.path}")
        self._info: DatasetInfo | None = None

    @abstractmethod
    def _probe(self) -> DatasetInfo: ...

    def probe(self) -> DatasetInfo:
        if self._info is None:
            self._info = self._probe()
        return self._info

    def _scene(self, selection: VolumeSelection) -> SceneInfo:
        info = self.probe()
        if not 0 <= selection.scene < len(info.scenes):
            raise SelectionError(
                f"Scene index {selection.scene} is outside 0..{len(info.scenes) - 1}."
            )
        scene = info.scenes[selection.scene]
        selection_bounds(scene, selection)
        return scene

    def selected_shape(self, selection: VolumeSelection) -> tuple[int, int, int]:
        scene = self._scene(selection)
        return selection_bounds(scene, selection)[2]

    @abstractmethod
    def _read_region(
        self,
        selection: VolumeSelection,
        region: tuple[slice, slice, slice],
    ) -> NDArray[np.generic]: ...

    def read_region(
        self,
        selection: VolumeSelection,
        region: tuple[slice, slice, slice],
    ) -> NDArray[np.generic]:
        shape = self.selected_shape(selection)
        normalized = normalize_region(region, shape)
        result = np.asarray(self._read_region(selection, normalized))
        expected = tuple(item.stop - item.start for item in normalized)
        if result.ndim != 3 or result.shape != expected:
            raise SelectionError(
                f"Reader returned shape {result.shape}; expected canonical ZYX shape {expected}."
            )
        return result

    def read_plane(
        self,
        selection: VolumeSelection,
        z: int,
        y: slice = slice(None),
        x: slice = slice(None),
    ) -> NDArray[np.generic]:
        """Decode one plane; the returned array is two-dimensional ``YX``."""

        shape = self.selected_shape(selection)
        if not 0 <= z < shape[0]:
            raise SelectionError(f"Z index {z} is outside 0..{shape[0] - 1}.")
        return self.read_region(selection, (slice(z, z + 1), y, x))[0]

    def iter_chunks(
        self,
        selection: VolumeSelection,
        chunk_shape: tuple[int, int, int],
    ) -> Iterator[VolumeChunk]:
        shape = self.selected_shape(selection)
        for region in chunk_slices(shape, chunk_shape):
            yield VolumeChunk(region, self.read_region(selection, region))
