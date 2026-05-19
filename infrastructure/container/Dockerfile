# ──────────────────────────────────────────────────────────────────────────────
# Weather Pipeline — Docker Image (deps-only, multi-stage)
# ──────────────────────────────────────────────────────────────────────────────
# Contains the conda environment and system tools ONLY.
# Source code is bind-mounted at runtime → no rebuild needed for code changes.
#
# Rebuild only when weather_env.yml changes (new/removed packages).
#
# Build:
#   docker build -f infrastructure/container/Dockerfile -t weather .
#
# Run (mount source + data):
#   docker run --rm \
#       -v "$(pwd)/src":/app/src \
#       -v "$(pwd)/data/cosmo_rea6":/data \
#       -e COSMO_WORK_DIR=/data \
#       weather \
#       python -m weather run --provider cosmo-rea6 --months 1
#
# Or use docker-compose (recommended for local development):
#   docker compose -f infrastructure/container/docker-compose.yml up
#
# Use with Apptainer on HPC:
#   docker push <registry>/weather:latest
#   apptainer pull docker://<registry>/weather:latest
# ──────────────────────────────────────────────────────────────────────────────

FROM continuumio/miniconda3:24.1.2-0 AS builder

# Install system tools for decompression
RUN apt-get update \
    && apt-get install -y --no-install-recommends lbzip2 pbzip2 \
    && rm -rf /var/lib/apt/lists/*

# Create the conda environment from the pinned spec file
COPY infrastructure/env/weather_env.yml /tmp/weather_env.yml
RUN conda env create -f /tmp/weather_env.yml \
    && conda clean -afy \
    && rm /tmp/weather_env.yml

# ── Runtime stage ─────────────────────────────────────────────────────────
FROM continuumio/miniconda3:24.1.2-0

LABEL org.opencontainers.image.source="https://github.com/UU-BUEM/weather"
LABEL org.opencontainers.image.description="Weather pipeline for UU-BUEM"
LABEL org.opencontainers.image.licenses="MIT"

RUN apt-get update \
    && apt-get install -y --no-install-recommends lbzip2 pbzip2 curl \
    && rm -rf /var/lib/apt/lists/*

# Copy the pre-built conda environment from builder
COPY --from=builder /opt/conda/envs/weather_env /opt/conda/envs/weather_env

# Activate environment
ENV PATH=/opt/conda/envs/weather_env/bin:$PATH
ENV CONDA_DEFAULT_ENV=weather_env

# Source code is bind-mounted at /app/src at runtime
ENV PYTHONPATH=/app/src

# Workaround for NetCDF4/HDF5 on NFS/Lustre filesystems
ENV HDF5_USE_FILE_LOCKING=FALSE

WORKDIR /app

# Default: show resolved pipeline configuration
CMD ["python", "-m", "weather", "info"]
