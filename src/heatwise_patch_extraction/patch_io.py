# -*- coding: utf-8 -*-
"""Write out the final patch H5 dataset."""
from __future__ import annotations

import os

import h5py
import numpy as np


def write_patch_h5(
    h5_path: str,
    sen2: np.ndarray,
    hsi_bs: np.ndarray,
    label_onehot: np.ndarray,
    split: np.ndarray,
    geo_isolated: np.ndarray,
    coords: np.ndarray,
    class_order: list[int],
    block_m: float,
    super_block_m: float,
    hsi_pca: np.ndarray | None = None,
    lst: np.ndarray | None = None,
    lst_valid: np.ndarray | None = None,
) -> None:
    os.makedirs(os.path.dirname(h5_path) or ".", exist_ok=True)
    with h5py.File(h5_path, "w") as f:
        f.create_dataset("sen2", data=sen2)
        f.create_dataset("hsi_bs", data=hsi_bs)
        f.create_dataset("label", data=label_onehot)
        f.create_dataset("split", data=split)                # 0=train 1=val 2=test
        f.create_dataset("geo_isolated", data=geo_isolated)   # 1=geographically isolated, 0=random split (rare class)
        f.create_dataset("coords", data=coords)
        if hsi_pca is not None:
            f.create_dataset("hsi_pca", data=hsi_pca)
        if lst is not None:
            f.create_dataset("lst", data=lst)
            f.create_dataset("lst_valid", data=lst_valid)
        f.attrs["class_order"] = np.array(class_order, dtype=np.int32)
        f.attrs["split_meaning"] = "0=train,1=val,2=test"
        f.attrs["block_m"] = block_m
        f.attrs["super_block_m"] = super_block_m if super_block_m else 0
    print(f"[patch_io] Saved: {h5_path}  sen2{sen2.shape}  hsi_bs{hsi_bs.shape}"
          + (f"  hsi_pca{hsi_pca.shape}" if hsi_pca is not None else "")
          + (f"  lst{lst.shape}" if lst is not None else ""))
