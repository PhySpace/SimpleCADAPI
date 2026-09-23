ARG NODE_IMAGE=node:22-bookworm-slim@sha256:48e4b67d85f87bd551df43704e24d252f56cc5f8e9718841aace50f19948f0f9
ARG BASE_IMAGE=python:3.12-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a
ARG CODEX_VERSION

FROM ${NODE_IMAGE} AS codex-cli
ARG CODEX_VERSION
RUN npm install --global --omit=dev "@openai/codex@${CODEX_VERSION}" \
    && code_mode_host="$(find /usr/local/lib/node_modules/@openai/codex \
        -type f -path '*/vendor/*/bin/codex-code-mode-host' -print -quit)" \
    && test -n "${code_mode_host}" \
    && test "$(codex --version)" = "codex-cli ${CODEX_VERSION}"

FROM ${BASE_IMAGE}

ARG CODEX_VERSION
ENV DEBIAN_FRONTEND=noninteractive \
    PATH=/opt/cad-venv/bin:${PATH} \
    PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash ca-certificates curl git ripgrep \
    libgl1 libglu1-mesa libx11-6 libxext6 libxrender1 libxinerama1 \
    libxrandr2 libxcursor1 libxi6 libsm6 libice6 libfontconfig1 libosmesa6 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=codex-cli /usr/local /usr/local
RUN test "$(codex --version)" = "codex-cli ${CODEX_VERSION}" \
    && code_mode_host="$(find /usr/local/lib/node_modules/@openai/codex \
        -type f -path '*/vendor/*/bin/codex-code-mode-host' -print -quit)" \
    && test -x "${code_mode_host}"
RUN python -m venv /opt/cad-venv
COPY source /opt/simplecadapi
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install /opt/simplecadapi PyYAML==6.0.2 \
    && python -m pip freeze --all > /opt/cad-runtime-pip-freeze.txt
COPY source/docs/skill /skills/simplecadapi
RUN test -x /opt/cad-venv/bin/sca && test -r /skills/simplecadapi/SKILL.md
WORKDIR /workspace
