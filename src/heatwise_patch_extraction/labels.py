# -*- coding: utf-8 -*-
"""Labels (KML/XML) -> Shapefile, and polygon loading/filtering."""
from __future__ import annotations

import os

import geopandas as gpd


def kml_to_shp(kml_path: str, shp_path: str, target_epsg: str) -> str:
    """KML (XML) -> reproject to target_epsg -> save as Shapefile."""
    gdf = gpd.read_file(kml_path, driver="KML")
    gdf = gdf.to_crs(target_epsg)
    os.makedirs(os.path.dirname(shp_path) or ".", exist_ok=True)
    gdf.to_file(shp_path, driver="ESRI Shapefile")
    print(f"[labels] Converted to Shapefile: {shp_path}  ({len(gdf)} features)")
    return shp_path


def ensure_shapefile(kml_path: str | None, shp_path: str, target_epsg: str) -> str:
    """Use shp_path directly if it already exists; otherwise convert it from kml_path."""
    if os.path.exists(shp_path):
        print(f"[labels] Using existing Shapefile: {shp_path}")
        return shp_path
    if not kml_path:
        raise ValueError(f"{shp_path} does not exist, and no kml was provided to generate it.")
    return kml_to_shp(kml_path, shp_path, target_epsg)


def load_polygons(shp_path: str, class_column: str, min_area: float):
    polygons = gpd.read_file(shp_path)
    n0 = len(polygons)
    polygons = polygons[polygons.geometry.area >= min_area].copy()
    print(f"[labels] Polygons: {n0} -> {len(polygons)} after area filtering")
    print("[labels] Class distribution:\n", polygons[class_column].value_counts())
    return polygons
