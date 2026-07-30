# syntax=docker/dockerfile:1.9
FROM python:3.12-slim

# Inherit build arguments for labels
# Pinned: the unpinned `uv pip install --upgrade` was silently pulling the
# latest graphiti-core (and transitively bumping openai/neo4j/pydantic majors)
# on every uncached build. Bump this deliberately, never implicitly.
ARG GRAPHITI_VERSION=0.29.2
# `redis` arrives TRANSITIVELY via graphiti-core[falkordb] and is resolved by the
# `uv pip install` below, OUTSIDE uv.lock — so it floats on every uncached build.
# redis 8.1.0 breaks falkordb's Is_Cluster() (forwards async connection kwargs
# into a sync Redis(**kwargs) -> unexpected keyword 'himport_registry') and the
# app dies in FalkorDriver.__init__. 8.0.1 is the last version known to boot.
ARG REDIS_VERSION=8.0.1
ARG BUILD_DATE
ARG VCS_REF

# OCI image annotations
LABEL org.opencontainers.image.title="Graphiti FastAPI Server"
LABEL org.opencontainers.image.description="FastAPI server for Graphiti temporal knowledge graphs"
LABEL org.opencontainers.image.version="${GRAPHITI_VERSION}"
LABEL org.opencontainers.image.created="${BUILD_DATE}"
LABEL org.opencontainers.image.revision="${VCS_REF}"
LABEL org.opencontainers.image.vendor="Zep AI"
LABEL org.opencontainers.image.source="https://github.com/getzep/graphiti"
LABEL org.opencontainers.image.documentation="https://github.com/getzep/graphiti/tree/main/server"
LABEL io.graphiti.core.version="${GRAPHITI_VERSION}"

# Install uv using the installer script
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ADD https://astral.sh/uv/install.sh /uv-installer.sh
RUN sh /uv-installer.sh && rm /uv-installer.sh
ENV PATH="/root/.local/bin:$PATH"

# Configure uv for runtime
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Create non-root user
RUN groupadd -r app && useradd -r -d /app -g app app

# Set up the server application first
WORKDIR /app
COPY ./server/pyproject.toml ./server/README.md ./server/uv.lock ./
COPY ./server/graph_service ./graph_service

# Install server dependencies (without graphiti-core from lockfile)
# Then install graphiti-core from PyPI at the desired version
# This prevents the stale lockfile from pinning an old graphiti-core version
ARG INSTALL_FALKORDB=true
RUN --mount=type=cache,target=/root/.cache/uv,id=s/a5e8d61f-bfe2-4d50-be77-ef89cb4bc46e-uv-cache \
    uv sync --frozen --no-dev && \
    if [ -n "$GRAPHITI_VERSION" ]; then \
        if [ "$INSTALL_FALKORDB" = "true" ]; then \
            uv pip install --upgrade "graphiti-core[falkordb]==$GRAPHITI_VERSION" "redis==$REDIS_VERSION"; \
        else \
            uv pip install --upgrade "graphiti-core==$GRAPHITI_VERSION"; \
        fi; \
    else \
        if [ "$INSTALL_FALKORDB" = "true" ]; then \
            uv pip install --upgrade "graphiti-core[falkordb]"; \
        else \
            uv pip install --upgrade graphiti-core; \
        fi; \
    fi

# Overlay local fixes onto the installed graphiti-core
# (graphiti-core is installed from PyPI above — the repo's graphiti_core/
# source tree is NOT what runs, so library fixes must be copied over the
# site-packages install). Fixes: single-group read routing (upstream
# #1161/#1325, unmerged PRs #1170/#1326) and driver connection hardening.
# Drop these COPYs when a released graphiti-core contains the fixes
# and the GRAPHITI_VERSION pin is bumped past it.
COPY ./graphiti_core/decorators.py /app/.venv/lib/python3.12/site-packages/graphiti_core/decorators.py
COPY ./graphiti_core/driver/falkordb_driver.py /app/.venv/lib/python3.12/site-packages/graphiti_core/driver/falkordb_driver.py
# add_episode insert-or-update for supplied uuids: upstream 0.29.2 treats a
# supplied uuid as UPDATE-ONLY (get_by_uuid raises NodeNotFoundError for a
# first-time episode, so the ingest worker drops the job after the API already
# returned 202). Every deterministic-uuid writer (the nightly n8n ingest jobs,
# the concierge remember tool) depends on insert-or-update semantics.
COPY ./graphiti_core/graphiti.py /app/.venv/lib/python3.12/site-packages/graphiti_core/graphiti.py
# FalkorDB label-expression fix: upstream builds Neo4j-5 label expressions
# (`n:A|B`) for multi-label search filters. FalkorDB does not implement label
# expressions (FalkorDB#458), so EVERY multi-type search fails the whole query
# with a parse error — rewritten to the parenthesised OR-form FalkorDB
# documents. Without this COPY, that fix is silently inert.
COPY ./graphiti_core/search/search_filters.py /app/.venv/lib/python3.12/site-packages/graphiti_core/search/search_filters.py

# Change ownership to app user
RUN chown -R app:app /app

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Switch to non-root user
USER app

# Set port
ENV PORT=8000
EXPOSE $PORT

CMD ["uvicorn", "graph_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
