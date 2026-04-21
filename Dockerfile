# OpenSVF Docker Image
# Provides a complete, reproducible SVF environment:
#   - Python 3.11 + all pip deps
#   - OpenJDK 21 (for YAMCS)
#   - YAMCS 5.12.6 pre-installed
#   - Eclipse Cyclone DDS
#   - FMU binaries included
#   - obsw_sim binary included
#
# Usage:
#   docker build -t opensvf .
#   docker run --rm opensvf testosvf
#   docker run --rm -p 8090:8090 opensvf bash scripts/demo.sh

FROM ubuntu:24.04

# Prevent interactive prompts during apt
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# ------------------------------------------------------------------ #
# 1. System dependencies                                              #
# ------------------------------------------------------------------ #
RUN apt-get update --fix-missing && apt-get install -y --no-install-recommends \
    # Python
    python3 \
    python3-venv \
    python3-pip \
    # Java (for YAMCS)
    openjdk-21-jre-headless \
    # Build tools (for pip packages that compile C extensions)
    gcc \
    g++ \
    make \
    # Utilities
    curl \
    git \
    ca-certificates \
    # Cyclone DDS runtime dependency
    libssl3 \
    && rm -rf /var/lib/apt/lists/*

# ------------------------------------------------------------------ #
# 2. YAMCS                                                            #
# ------------------------------------------------------------------ #
RUN mkdir -p /opt/yamcs && \
    curl -sL https://github.com/yamcs/yamcs/releases/download/yamcs-5.12.6/yamcs-5.12.6-linux-x86_64.tar.gz \
        -o /tmp/yamcs.tar.gz && \
    tar -xzf /tmp/yamcs.tar.gz -C /opt/yamcs --strip-components=1 && \
    rm /tmp/yamcs.tar.gz

ENV YAMCS_HOME=/opt/yamcs
ENV PATH="$YAMCS_HOME/bin:$PATH"

# ------------------------------------------------------------------ #
# 3. Application                                                      #
# ------------------------------------------------------------------ #
WORKDIR /opensvf

# Copy dependency files first (layer cache)
COPY pyproject.toml ./
COPY src/ src/

# Create venv and install deps
RUN python3 -m venv /opensvf/.venv && \
    /opensvf/.venv/bin/pip install --upgrade pip && \
    /opensvf/.venv/bin/pip install -e ".[dev]"

ENV PATH="/opensvf/.venv/bin:$PATH"

ENV PATH="/opensvf/.venv/bin:$PATH"
ENV VIRTUAL_ENV="/opensvf/.venv"

# Copy the rest of the repo
COPY . .

# Fix obsw_sim permissions
RUN chmod +x obsw_sim 2>/dev/null || true

# Fix YAMCS XTCE path and pre-generate MDB
RUN python3 tools/generate_xtce.py > yamcs/mdb/opensvf.xml && \
    sed -i "s|spec: \".*yamcs/mdb/opensvf.xml\"|spec: \"/opensvf/yamcs/mdb/opensvf.xml\"|" \
        yamcs/etc/yamcs.opensvf.yaml

# ------------------------------------------------------------------ #
# 4. Aliases as wrapper scripts                                       #
# ------------------------------------------------------------------ #
RUN echo '#!/bin/bash\npytest tests/ --junitxml=results/junit.xml -v "$@"' \
        > /usr/local/bin/testosvf && chmod +x /usr/local/bin/testosvf && \
    echo '#!/bin/bash\nmypy src/ --config-file pyproject.toml "$@"' \
        > /usr/local/bin/checkosvf && chmod +x /usr/local/bin/checkosvf && \
    echo '#!/bin/bash\n/opt/yamcs/bin/yamcsd --etc-dir /opensvf/yamcs/etc "$@"' \
        > /usr/local/bin/yamcs-start && chmod +x /usr/local/bin/yamcs-start

# ------------------------------------------------------------------ #
# 5. Healthcheck + default command                                    #
# ------------------------------------------------------------------ #
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python3 -c "import svf; print('OK')" || exit 1

EXPOSE 8090 10015 10025

CMD ["testosvf"]
