# -*- coding: utf-8 -*-
"""
Geographically isolated (spatial block hold-out) split: assign candidate
patches to train/val/test by super-block; any patch whose footprint spans
blocks belonging to different splits is dropped (isolation buffer), guaranteeing
zero spatial overlap between the train and test regions.

Classes with too few super-blocks (e.g. sample distribution is too narrow, such
as a class with only one small polygon) cannot be geographically isolated and
fall back to a random stratified split for their patches (patch-level
separation only, not full geographic isolation).
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np


def touched_blocks(x, y, patch_size: int, resolution: float, block_m: float):
    """List of blocks (bx, by) covered by a patch's footprint."""
    h = (patch_size / 2) * resolution
    bx0, bx1 = int(np.floor((x - h) / block_m)), int(np.floor((x + h) / block_m))
    by0, by1 = int(np.floor((y - h) / block_m)), int(np.floor((y + h) / block_m))
    return [(bx, by) for bx in range(bx0, bx1 + 1) for by in range(by0, by1 + 1)]


def run_geo_split(
    P_xy: np.ndarray,
    P_lab: np.ndarray,
    class_order: list[int],
    patch_size: int,
    resolution: float,
    block_m: float,
    super_block_m: float,
    split_ratio: tuple[float, float, float] = (0.6, 0.2, 0.2),
    min_sb_for_geo: int = 3,
    seed_search: int = 300,
    random_seed: int = 42,
):
    B, S = block_m, super_block_m

    def super_of(bx, by):
        return (int(np.floor(bx * B / S)), int(np.floor(by * B / S))) if S else (bx, by)

    patch_blocks = [touched_blocks(x, y, patch_size, resolution, B) for x, y in P_xy]
    center_super = [super_of(int(np.floor(x / B)), int(np.floor(y / B))) for x, y in P_xy]
    block_set = sorted({b for bl in patch_blocks for b in bl})
    supers = sorted({super_of(*b) for b in block_set})

    cls_sb = defaultdict(set)
    for i in range(len(P_lab)):
        cls_sb[int(P_lab[i])].add(center_super[i])
    non_iso = {c for c, sb in cls_sb.items() if len(sb) < min_sb_for_geo}
    iso = sorted(set(cls_sb) - non_iso)
    present = [c for c in class_order if (P_lab == c).any()]
    print(f"[geo_split] Super-blocks: {len(supers)} (edge {S} m) | geo-isolatable classes: {iso}")
    print(f"[geo_split] Classes falling back to random split (too few super-blocks): "
          f"{[(c, len(cls_sb[c])) for c in sorted(non_iso)]}")

    def assign(seed):
        r = np.random.default_rng(seed)
        sidx = r.permutation(len(supers))
        n_str = int(round(split_ratio[0] * len(supers)))
        n_sva = int(round(split_ratio[1] * len(supers)))
        ssp = {supers[s]: (0 if k < n_str else (1 if k < n_str + n_sva else 2)) for k, s in enumerate(sidx)}
        bsp = {b: ssp[super_of(*b)] for b in block_set}
        sp = np.full(len(P_lab), -1, dtype="int8")
        gf = np.zeros(len(P_lab), dtype="int8")
        rbc = defaultdict(list)
        nb = 0
        for i, bl in enumerate(patch_blocks):
            if int(P_lab[i]) in non_iso:
                rbc[int(P_lab[i])].append(i)
                continue
            s = {bsp[b] for b in bl}
            if len(s) == 1:
                sp[i] = s.pop()
                gf[i] = 1
            else:
                nb += 1
        for c, idxs in rbc.items():
            idxs = np.array(idxs)
            r.shuffle(idxs)
            n = len(idxs)
            a = int(round(split_ratio[0] * n))
            b2 = int(round(split_ratio[1] * n))
            sp[idxs[:a]] = 0
            sp[idxs[a:a + b2]] = 1
            sp[idxs[a + b2:]] = 2
        return sp, gf, nb

    def score(sp):
        kl = P_lab[sp >= 0]
        ks = sp[sp >= 0]
        cells = [int(((kl == c) & (ks == s)).sum()) for c in present for s in range(3)]
        return (sum(v == 0 for v in cells), -min(cells) if cells else 0)

    if seed_search and seed_search > 0:
        best = None
        for seed in range(seed_search):
            sp, gf, nb = assign(seed)
            sc = score(sp)
            if best is None or sc < best[0]:
                best = (sc, seed, sp, gf, nb)
        _, seed, split, geo_flag, n_border = best
        print(f"[geo_split] Searched {seed_search} seeds -> chose seed={seed} "
              f"(zero-coverage cells={best[0][0]}, min cell={-best[0][1]})")
    else:
        split, geo_flag, n_border = assign(random_seed)
        print(f"[geo_split] Using fixed seed={random_seed}")

    print(f"[geo_split] Patches dropped at split boundaries for geo-isolated classes: "
          f"{n_border} ({100 * n_border / max(len(P_lab), 1):.1f}%)")

    diagnostics = {"non_iso_classes": sorted(non_iso), "n_border_dropped": n_border, "n_supers": len(supers)}
    return split, geo_flag, diagnostics
