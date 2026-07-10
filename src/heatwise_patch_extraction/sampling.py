# -*- coding: utf-8 -*-
"""Grid sampling + patch extraction (sen2/hsi/pca/lst share the same windowing mechanism)."""
from __future__ import annotations

import numpy as np
import rasterio.windows
from rasterio.windows import Window
from shapely.geometry import Point


def grid_sample_within_polygon(poly, grid_patch_size: int, resolution: float):
    """Sample points on a regular grid inside a polygon (spacing = grid_patch_size * resolution meters)."""
    spacing = grid_patch_size * resolution
    minx, miny, maxx, maxy = poly.bounds
    pts = []
    for x in np.arange(minx + spacing / 2, maxx, spacing):
        for y in np.arange(miny + spacing / 2, maxy, spacing):
            p = Point(x, y)
            if poly.contains(p):
                pts.append(p)
    return pts


def extract_patch(img, point, size: int):
    """Extract a size x size patch centered on point; returns (None, None) if out of bounds."""
    row, col = img.index(point.x, point.y)
    half = size // 2
    window = Window(col - half, row - half, size, size)
    if (window.col_off < 0 or window.row_off < 0 or
            window.col_off + size > img.width or
            window.row_off + size > img.height):
        return None, None
    return img.read(window=window), window


def extract_window_from_array(arr: np.ndarray, inv_transform, point_xy, size: int):
    """Extract a size x size window from an in-memory array (e.g. an already
    normalized LST raster) centered on a coordinate. Returns None if out of
    bounds. arr: (H, W)."""
    H, W = arr.shape
    half = size // 2
    c, r = inv_transform * point_xy
    c, r = int(np.floor(c)), int(np.floor(r))
    if r - half < 0 or c - half < 0 or r + half > H or c + half > W:
        return None
    return arr[r - half:r + half, c - half:c + half].copy()


def is_empty_patch(patch, nodata) -> bool:
    """A patch is considered empty/invalid if it contains NaN, is all-zero, or
    contains the image's nodata value."""
    if patch is None:
        return True
    if np.isnan(patch).any():
        return True
    if np.all(patch == 0):
        return True
    if nodata is not None and np.any(patch == nodata):
        return True
    return False


def overlap_threshold_for(label, overlap_threshold: float, overlap_threshold_by_class: dict) -> float:
    return overlap_threshold_by_class.get(int(label), overlap_threshold)


def patch_overlap_ratio(window, transform, polygons, class_column, label):
    """Given the sen2 patch window, compute the maximum overlap ratio against
    the polygons belonging to its class."""
    from shapely.geometry import box
    patch_geom = box(*rasterio.windows.bounds(window, transform))
    class_polys = polygons[polygons[class_column] == label]
    overlaps = [patch_geom.intersection(poly).area / patch_geom.area
                for poly in class_polys.geometry if patch_geom.intersects(poly)]
    return max(overlaps) if overlaps else 0.0
