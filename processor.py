#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
HEATWISE patch extraction CLI.

Given one city's polygon labels (KML or SHP) + Sentinel-2 / HSI (+ optional
LST / PCA) rasters, grid-samples points inside each labeled polygon, extracts
aligned patches, and writes a single geographically-isolated H5 dataset
(train/val/test via a "super-block" spatial hold-out split).

Usage:
    python processor.py --config config/example_config.yaml
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import numpy as np
import rasterio
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.heatwise_patch_extraction.labels import ensure_shapefile, load_polygons
from src.heatwise_patch_extraction.sampling import (
    grid_sample_within_polygon, extract_patch, extract_window_from_array,
    is_empty_patch, overlap_threshold_for, patch_overlap_ratio,
)
from src.heatwise_patch_extraction.geo_split import run_geo_split
from src.heatwise_patch_extraction.patch_io import write_patch_h5


def run_extraction(cfg: dict) -> None:
    random_seed = cfg.get("split", {}).get("random_seed", 42)
    random.seed(random_seed)
    np.random.seed(random_seed)

    city = cfg["city"]
    target_epsg = cfg["target_epsg"]
    inputs = cfg["inputs"]
    labels_cfg = cfg["labels"]
    sampling_cfg = cfg.get("sampling", {})
    split_cfg = cfg.get("split", {})
    toggles = cfg.get("toggles", {})
    use_lst = bool(toggles.get("use_lst", False))
    use_pca = bool(toggles.get("use_pca", False))

    class_column = labels_cfg["class_column"]
    min_area = labels_cfg["min_area"]
    remap_dict = {int(k): int(v) for k, v in labels_cfg["remap_dict"].items()}
    class_order = [int(c) for c in labels_cfg["class_order"]]
    overlap_threshold = labels_cfg.get("overlap_threshold", 0.6)
    overlap_threshold_by_class = {int(k): float(v) for k, v in labels_cfg.get("overlap_threshold_by_class", {}).items()}

    grid_patch_size = sampling_cfg.get("grid_patch_size", 8)
    resolution = sampling_cfg.get("resolution", 10)
    patch_size = sampling_cfg.get("patch_size", 32)

    shp_path = labels_cfg.get("shp") or f"{Path(labels_cfg.get('kml', city)).with_suffix('')}.shp"
    shp_path = ensure_shapefile(labels_cfg.get("kml"), shp_path, target_epsg)
    polygons = load_polygons(shp_path, class_column, min_area)

    sen2_img = rasterio.open(inputs["sentinel2"])
    hsi_img = rasterio.open(inputs["hsi"])
    pca_img = rasterio.open(inputs["pca"]) if use_pca and inputs.get("pca") else None
    lst_arr = lst_inv = lst_nodata = None
    if use_lst and inputs.get("lst"):
        with rasterio.open(inputs["lst"]) as lst_src:
            lst_arr = lst_src.read(1).astype("float32")
            lst_inv = ~lst_src.transform
            lst_nodata = lst_src.nodata if lst_src.nodata is not None else -9999.0

    print(f"[processor] city={city}  bands  sen2={sen2_img.count}  hsi={hsi_img.count}"
          + (f"  pca={pca_img.count}" if pca_img else "")
          + (f"  lst={'on' if lst_arr is not None else 'off'}"))

    all_points = []
    for label in polygons[class_column].unique():
        for _, row in polygons[polygons[class_column] == label].iterrows():
            pts = grid_sample_within_polygon(row.geometry, grid_patch_size, resolution)
            all_points.extend([(p, label) for p in pts])
    print(f"[processor] Sample points: {len(all_points)}")

    P_sen2, P_hsi, P_pca, P_lst, P_lst_valid, P_xy, P_lab = [], [], [], [], [], [], []
    n_oob = n_overlap = n_empty = n_unmapped = 0

    for point, label in all_points:
        sen2_patch, sen2_win = extract_patch(sen2_img, point, patch_size)
        hsi_patch, _ = extract_patch(hsi_img, point, patch_size)
        pca_patch = None
        if pca_img is not None:
            pca_patch, _ = extract_patch(pca_img, point, patch_size)
            if pca_patch is None:
                n_oob += 1
                continue
        if sen2_patch is None or hsi_patch is None:
            n_oob += 1
            continue

        thr = overlap_threshold_for(label, overlap_threshold, overlap_threshold_by_class)
        if patch_overlap_ratio(sen2_win, sen2_img.transform, polygons, class_column, label) < thr:
            n_overlap += 1
            continue

        if (is_empty_patch(sen2_patch, sen2_img.nodata) or
                is_empty_patch(hsi_patch, hsi_img.nodata) or
                (pca_patch is not None and is_empty_patch(pca_patch, pca_img.nodata))):
            n_empty += 1
            continue

        orig = int(label)
        if orig not in remap_dict:
            n_unmapped += 1
            continue

        lst_win = None
        lst_valid_flag = 1
        if lst_arr is not None:
            lst_win = extract_window_from_array(lst_arr, lst_inv, (point.x, point.y), patch_size)
            if lst_win is None:
                lst_valid_flag = 0
                lst_win = np.zeros((patch_size, patch_size), dtype="float32")
            else:
                bad = (lst_win == lst_nodata) | ~np.isfinite(lst_win)
                if bad.any():
                    lst_valid_flag = 0
                    good = lst_win[~bad]
                    fill = float(good.mean()) if good.size else 0.0
                    lst_win = lst_win.copy()
                    lst_win[bad] = fill

        P_sen2.append(sen2_patch.transpose(1, 2, 0))
        P_hsi.append(hsi_patch.transpose(1, 2, 0))
        if pca_patch is not None:
            P_pca.append(pca_patch.transpose(1, 2, 0))
        if lst_arr is not None:
            P_lst.append(lst_win[:, :, None])
            P_lst_valid.append(lst_valid_flag)
        P_xy.append((point.x, point.y))
        P_lab.append(remap_dict[orig])

    sen2_img.close()
    hsi_img.close()
    if pca_img is not None:
        pca_img.close()

    print(f"[processor] Filtered: out_of_bounds={n_oob} low_overlap={n_overlap} empty={n_empty} unmapped={n_unmapped}")
    print(f"[processor] Valid candidate patches: {len(P_lab)}")
    if len(P_lab) == 0:
        raise SystemExit("No valid patches; check EPSG/paths/thresholds.")

    P_xy = np.array(P_xy)
    P_lab = np.array(P_lab)

    split, geo_flag, diagnostics = run_geo_split(
        P_xy=P_xy, P_lab=P_lab, class_order=class_order,
        patch_size=patch_size, resolution=resolution,
        block_m=split_cfg.get("block_m", 500.0),
        super_block_m=split_cfg.get("super_block_m", 2500.0),
        split_ratio=tuple(split_cfg.get("split_ratio", (0.6, 0.2, 0.2))),
        min_sb_for_geo=split_cfg.get("min_sb_for_geo", 3),
        seed_search=split_cfg.get("seed_search", 300),
        random_seed=random_seed,
    )

    keep = np.where(split >= 0)[0]
    print(f"[processor] Kept patches: {len(keep)} / {len(P_lab)}")

    X_sen2 = np.array([P_sen2[i] for i in keep], dtype="float32")
    X_hsi = np.array([P_hsi[i] for i in keep], dtype="float32")
    X_pca = np.array([P_pca[i] for i in keep], dtype="float32") if P_pca else None
    if P_lst:
        X_lst = np.array([P_lst[i] for i in keep], dtype="float32")
        X_lst_valid = np.array([P_lst_valid[i] for i in keep], dtype="int8")
    else:
        X_lst = X_lst_valid = None

    xy = P_xy[keep]
    lab = P_lab[keep]
    split = split[keep]
    geo_flag = geo_flag[keep]

    num_classes = len(class_order)
    c2i = {c: i for i, c in enumerate(class_order)}
    y_onehot = np.eye(num_classes, dtype="float32")[[c2i[int(c)] for c in lab]]

    names = ["train", "val", "test"]
    present = [c for c in class_order if (lab == c).any()]
    print("\n[processor] Patch count per split x class:")
    for c in present:
        cnt = [int(((lab == c) & (split == s)).sum()) for s in range(3)]
        print(f"  class {c}: " + " ".join(f"{n}={v}" for n, v in zip(names, cnt)))

    write_patch_h5(
        h5_path=cfg["output"]["h5_path"],
        sen2=X_sen2, hsi_bs=X_hsi, label_onehot=y_onehot,
        split=split, geo_isolated=geo_flag, coords=xy,
        class_order=class_order,
        block_m=split_cfg.get("block_m", 500.0),
        super_block_m=split_cfg.get("super_block_m", 2500.0),
        hsi_pca=X_pca, lst=X_lst, lst_valid=X_lst_valid,
    )


def main():
    parser = argparse.ArgumentParser(description="HEATWISE geo-isolated patch extraction")
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-h5", help="Overrides the config's `output.h5_path` if given")
    args = parser.parse_args()
    with open(args.config, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if args.output_h5:
        cfg.setdefault("output", {})["h5_path"] = args.output_h5
    run_extraction(cfg)


if __name__ == "__main__":
    main()
