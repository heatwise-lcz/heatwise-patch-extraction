# heatwise-patch-extraction: geo-isolated patch extraction EOAP processor.
#
# geopandas/shapely/fiona need GEOS/PROJ/GDAL; install the system libraries
# so pip wheels resolve cleanly (mirrors heatwise-hsi-lst-prep's Dockerfile).
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libexpat1 \
    libgdal-dev \
    gdal-bin \
    && rm -rf /var/lib/apt/lists/*

# cwltool (and some other CWL runners) run the container as an arbitrary
# numeric UID (--user=1000:1000 by default) with no matching /etc/passwd
# entry. Some libraries call getpass.getuser()/pwd.getpwuid() and crash with
# `KeyError: getpwuid(): uid not found` if that lookup fails -- confirmed by
# an actual cwltool run against heatwise-lcz-classification's identical setup
# (triggered deep inside torch's dynamo cache-dir resolution). Pre-creating a
# UID-1000 user here means the lookup succeeds regardless of which repo/deps
# end up calling it.
RUN useradd --create-home --uid 1000 --shell /bin/bash appuser

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Absolute path: under CWL, cwltool overrides the container's working
# directory to its own empty per-job staging dir (not WORKDIR /app above),
# and a relative ENTRYPOINT arg would then fail to resolve -- confirmed by
# an actual cwltool run (`python: can't open file '/<job-tmp>/processor.py'`,
# because ENTRYPOINT args are *appended to*, not replaced by, `docker run`
# arguments, unlike CMD).
ENTRYPOINT ["python", "/app/processor.py"]
