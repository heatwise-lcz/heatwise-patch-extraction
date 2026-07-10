cwlVersion: v1.2
class: CommandLineTool

label: HEATWISE Geo-Isolated Patch Extraction
doc: >
  EOAP-compatible HEATWISE patch extraction processor. Given a city's polygon
  labels (KML/SHP) plus Sentinel-2 / HSI (+ optional LST / PCA) rasters, grid
  samples points inside each labeled polygon, extracts aligned patches, and
  writes a single geographically-isolated H5 dataset (train/val/test via a
  "super-block" spatial hold-out split).

  The config file's `inputs.*`/`labels.*` paths are resolved against the
  container's working directory. Under `cwltool`, that working directory is
  an empty per-job staging directory, NOT the image's Dockerfile `WORKDIR
  /app`. So for this to work under CWL, every path *inside* the config must
  be an absolute `/app/...` path into the image (baked in via `COPY . .`)
  -- see `examples/sample_config_docker.yaml`. `examples/sample_config.yaml`
  (relative `./data/...` paths) is for local/non-Docker runs only.

  No `baseCommand`/entry-script `arguments` here on purpose: the image's
  `ENTRYPOINT` is `["python", "/app/processor.py"]` (absolute path, for the
  same cwltool-overrides-workdir reason as above). `docker run` arguments
  are *appended to* ENTRYPOINT, not a replacement for it (unlike `CMD`) --
  confirmed by an actual cwltool run that failed with `can't open file
  '/<job-tmp>/processor.py'` when this CWL redundantly also supplied
  `python`/`processor.py`, which then ran *in addition to* the ENTRYPOINT's
  own copy with a broken relative path. So this CWL only contributes the
  `--config`/`--output-h5` flags via inputBinding below.

requirements:
  DockerRequirement:
    # Release-shaped image reference. Before publishing, build/tag this
    # image locally with the same name so local cwltool runs exercise the
    # exact tag that will later be pushed to the registry.
    dockerImageId: ghcr.io/heatwise-lcz/heatwise-patch-extraction:0.1.0
    dockerPull: ghcr.io/heatwise-lcz/heatwise-patch-extraction:0.1.0

inputs:
  config:
    type: File
    inputBinding:
      prefix: --config
    doc: YAML config (see examples/sample_config_docker.yaml for the CWL/Docker variant). Its inputs.*/labels.* paths must resolve inside the container (i.e. reference data baked into the image via absolute /app/... paths).

  output_h5:
    type: string
    default: output/patches.h5
    inputBinding:
      prefix: --output-h5
    doc: Output H5 path (relative to the container working directory), overrides the config's output.h5_path.

outputs:
  patch_h5:
    type: File
    outputBinding:
      glob: $(inputs.output_h5)
    doc: The single output H5 patch dataset (sen2/hsi_bs/[hsi_pca]/[lst,lst_valid]/label/split/geo_isolated/coords).
