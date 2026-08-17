"""Image-resolved widest open path and bottleneck clearance.

This is a geometrical measurement inside a reviewed lumen mask.  It is not a
flow, pressure, or sweating measurement.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy import ndimage

from ._validation import as_bool_mask, as_zyx_array, validate_spacing_zyx

BoolArray = NDArray[np.bool_]


@dataclass(frozen=True, slots=True)
class BottleneckClearance:
    connected: bool
    bottleneck_radius_um: float | None
    bottleneck_diameter_um: float | None
    path_voxel_count: int
    inlet_open_voxels: int
    outlet_open_voxels: int
    path_mask: BoolArray
    qualification: str


def widest_open_path_clearance(
    lumen_mask: Any,
    plug_mask: Any,
    inlet_mask: Any,
    outlet_mask: Any,
    *,
    spacing_zyx_um: tuple[float, float, float],
) -> BottleneckClearance:
    """Maximize the minimum physical boundary distance over 6-neighbour paths.

    EDT values are distances to the complement of ``lumen & ~plug`` and respect
    anisotropic voxel sampling.  A maximum-capacity Dijkstra traversal finds the
    path whose narrowest voxel has the greatest clearance.
    """

    raw_lumen = as_zyx_array(lumen_mask, name="lumen_mask")
    lumen = as_bool_mask(raw_lumen, name="lumen_mask", shape=raw_lumen.shape)
    plug = as_bool_mask(plug_mask, name="plug_mask", shape=lumen.shape)
    inlet = as_bool_mask(inlet_mask, name="inlet_mask", shape=lumen.shape)
    outlet = as_bool_mask(outlet_mask, name="outlet_mask", shape=lumen.shape)
    spacing = validate_spacing_zyx(spacing_zyx_um)
    if np.any(plug & ~lumen):
        raise ValueError("plug_mask must be contained inside lumen_mask")
    open_mask = lumen & ~plug
    inlet_open = open_mask & inlet
    outlet_open = open_mask & outlet
    inlet_count = int(np.count_nonzero(inlet_open))
    outlet_count = int(np.count_nonzero(outlet_open))
    empty_path = np.zeros(lumen.shape, dtype=np.bool_)
    if inlet_count == 0 or outlet_count == 0:
        return BottleneckClearance(
            connected=False,
            bottleneck_radius_um=None,
            bottleneck_diameter_um=None,
            path_voxel_count=0,
            inlet_open_voxels=inlet_count,
            outlet_open_voxels=outlet_count,
            path_mask=empty_path,
            qualification="No image-resolved open inlet-to-outlet path in the reviewed volume.",
        )

    clearance = ndimage.distance_transform_edt(open_mask, sampling=spacing)
    capacity = np.full(lumen.shape, -1.0, dtype=np.float64)
    predecessor = np.full((*lumen.shape, 3), -1, dtype=np.int32)
    queue: list[tuple[float, int, int, int]] = []
    for z, y, x in zip(*np.nonzero(inlet_open), strict=True):
        value = float(clearance[z, y, x])
        capacity[z, y, x] = value
        heapq.heappush(queue, (-value, int(z), int(y), int(x)))

    offsets = ((-1, 0, 0), (1, 0, 0), (0, -1, 0), (0, 1, 0), (0, 0, -1), (0, 0, 1))
    target: tuple[int, int, int] | None = None
    shape = lumen.shape
    while queue:
        negative, z, y, x = heapq.heappop(queue)
        current = -negative
        if current < capacity[z, y, x]:
            continue
        if outlet_open[z, y, x]:
            target = (z, y, x)
            break
        for dz, dy, dx in offsets:
            nz, ny, nx = z + dz, y + dy, x + dx
            if not (0 <= nz < shape[0] and 0 <= ny < shape[1] and 0 <= nx < shape[2]):
                continue
            if not open_mask[nz, ny, nx]:
                continue
            candidate = min(current, float(clearance[nz, ny, nx]))
            if candidate > capacity[nz, ny, nx]:
                capacity[nz, ny, nx] = candidate
                predecessor[nz, ny, nx] = (z, y, x)
                heapq.heappush(queue, (-candidate, nz, ny, nx))

    if target is None:
        return BottleneckClearance(
            connected=False,
            bottleneck_radius_um=None,
            bottleneck_diameter_um=None,
            path_voxel_count=0,
            inlet_open_voxels=inlet_count,
            outlet_open_voxels=outlet_count,
            path_mask=empty_path,
            qualification="No image-resolved open inlet-to-outlet path in the reviewed volume.",
        )

    path = np.zeros(lumen.shape, dtype=np.bool_)
    cursor = target
    while True:
        path[cursor] = True
        previous = tuple(int(value) for value in predecessor[cursor])
        if previous[0] < 0:
            break
        cursor = previous
    radius = float(capacity[target])
    return BottleneckClearance(
        connected=True,
        bottleneck_radius_um=radius,
        bottleneck_diameter_um=2.0 * radius,
        path_voxel_count=int(np.count_nonzero(path)),
        inlet_open_voxels=inlet_count,
        outlet_open_voxels=outlet_count,
        path_mask=path,
        qualification=(
            "Image-resolved 6-neighbour geometry within the reviewed volume; not a flow or "
            "pressure measurement and limited by optical resolution."
        ),
    )
