# heatwise-patch-extraction

Stage 2 of the HEATWISE pipeline: turns a city's polygon labels (KML/SHP) plus
its Sentinel-2 / HSI (+ optional LST / PCA) rasters into a single H5 patch
dataset with a **geographically isolated** train/val/test split (super-block
spatial hold-out, so train and test patches never overlap in space).

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
python processor.py --config config/example_config.yaml
```

Copy `config/example_config.yaml` per city, point `inputs.*` at the outputs of
`heatwise-hsi-lst-prep`, and flip `toggles.use_lst` / `toggles.use_pca` on or
off as needed.

Output H5 fields:
- `sen2`, `hsi_bs`: patch stacks `(N, H, W, C)`
- `hsi_pca` (if `use_pca`): patch stack `(N, H, W, C)`
- `lst`, `lst_valid` (if `use_lst`): LST patch stack + per-patch validity flag
  (0 = patch touched a nodata/out-of-bounds edge and was filled with the
  patch-local mean)
- `label`: one-hot labels `(N, num_classes)`, dimension order = `class_order`
- `split`: 0=train, 1=val, 2=test
- `geo_isolated`: 1 if the patch's split came from full spatial isolation,
  0 if it came from the random-stratified fallback (classes with too few
  super-blocks to isolate geographically)
- `coords`: patch center coordinates in the target CRS

## Notes

- One run processes one city (the geo-split is inherently a single spatial
  domain); run it once per city and point `heatwise-lcz-classification`'s
  training step at a directory containing multiple H5 files to combine them.
- The old two-pass design (extract patches, then separately backfill an `lst`
  field into an existing H5 by coordinate lookup) has been folded into a
  single pass: LST windows are read from the same normalized raster that
  `heatwise-hsi-lst-prep` produces, using the same patch-center coordinates as
  the other modalities.
- `overlap_threshold_by_class` lets you override the minimum
  patch/polygon-overlap fraction per class (e.g. small polygons of a rare
  class need a lower threshold) instead of hardcoding it per city.
- **Important**: `inputs.*`/`labels.shp`/`labels.kml` paths in the config are
  resolved against the process's working directory, *not* the config file's
  own location (same convention as `heatwise-hsi-lst-prep`'s `wavelength_file`).
  Keep this in mind when running inside Docker/CWL -- see below.

## Sample data

`data/Berlin/` holds a self-contained test bundle (~57 MB) cropped to the
HEATWISE Berlin sample boundary (5.4 x 8.1 km): `Berlin_hsi_bs.tif` and
`Berlin_lst_final.tif` (outputs of `heatwise-hsi-lst-prep` run on its own
sample data), `Berlin_S2.tif`, and `Berlin_labels.shp` with 17 label
polygons across 8 LCZ classes. `examples/sample_config.yaml` is a
ready-to-use config pointing at it. Run from the repo root:

```bash
python processor.py --config examples/sample_config.yaml
```

This produces ~246 patches across 8 classes with a real geo-isolated
train/val/test split in about a minute.

## Docker

The image is built under its release-shaped name (registry namespace +
versioned tag, matching the CWL's `dockerPull`), so local tests exercise the
exact tag that will later be pushed to the registry:

```bash
docker build -t ghcr.io/heatwise-lcz/heatwise-patch-extraction:0.1.1 .

docker run --rm \
  -v /path/to/host/output:/app/output \
  ghcr.io/heatwise-lcz/heatwise-patch-extraction:0.1.1 \
  --config examples/sample_config.yaml --output-h5 /app/output/Berlin_patches.h5
```

Base image: `python:3.11-slim` + system `libgdal-dev`/`gdal-bin` (needed for
`geopandas`/`shapely`/`fiona`'s GDAL/GEOS/PROJ linkage), same pattern as
`heatwise-hsi-lst-prep`.

> The image has since been built and exercised repeatedly through `cwltool`
> runs (both standalone and as the `extract_patches` step of
> `heatwise-lcz-pipeline`).

## CWL

`heatwise_patch_extraction.cwl` describes the same interface (inputs:
`config` File, `output_h5` string; output: `patch_h5` File).
`examples/job.yaml` is a ready-to-use job order for the bundled sample data:

```bash
cd examples && cwltool ../heatwise_patch_extraction.cwl job.yaml
```

Because `inputs.*`/`labels.*` paths inside the config resolve against the
container's working directory rather than the config file's own location,
the referenced rasters/labels must already exist **inside the Docker image**
at those exact paths (baked in via `COPY . .`, which is why `data/Berlin/`
ships in the repo). **Two config variants exist** (same pattern as
`heatwise-hsi-lst-prep`, learned from an actual `cwltool` run there that
failed until fixed): `examples/sample_config.yaml` (relative `./data/...`
paths) for local/non-Docker runs, `examples/sample_config_docker.yaml`
(absolute `/app/data/...` paths) for Docker/CWL -- `cwltool` runs the
container with its own empty per-job working directory, not the image's
`WORKDIR /app`, so relative paths don't resolve there. `examples/job.yaml`
is wired to the `_docker` variant. The CWL's `arguments` also reference
`/app/processor.py` by absolute path for the same reason.

This repo is simpler than `heatwise-hsi-lst-prep`'s STAC catalog case (no
`secondaryFiles` juggling needed) because there's only one input file
(`config`) with paths inside it, not a catalog.json linking to sibling
item/asset files that `cwltool` would also need to stage.

> **Rebuild the image before testing this** (`docker build -t
> ghcr.io/heatwise-lcz/heatwise-patch-extraction:0.1.1 .`): the Dockerfile's `ENTRYPOINT` was
> just fixed too (`processor.py` -> `/app/processor.py`, absolute). An
> actual `cwltool` run against this repo failed with `can't open file
> '/<job-tmp>/processor.py'` because `ENTRYPOINT` args are *appended to*
> by `docker run` arguments, not replaced (unlike `CMD`) -- so the image's
> own relative `processor.py` ran (and failed) even though the CWL also
> (redundantly, and incorrectly) supplied `python /app/processor.py`. Fixed
> by making ENTRYPOINT itself absolute and removing the redundant
> `baseCommand`/arguments from this CWL file. `heatwise-hsi-lst-prep`'s CWL
> doesn't have this problem because its Dockerfile uses `CMD`, not
> `ENTRYPOINT`, and has been run successfully with `cwltool` end-to-end.
