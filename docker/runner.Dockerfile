FROM node:24-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends \
    dumb-init \
    python3 \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g pnpm@10.23.0

WORKDIR /deps/project
COPY openclaw-training-fork ./
RUN pnpm install --frozen-lockfile

COPY docker/runner.py /runner/runner.py

RUN useradd --system --create-home --home-dir /home/labuser --shell /usr/sbin/nologin labuser \
    && mkdir -p /runner-jobs /workspaces \
    && chown root:root /runner-jobs /workspaces /runner/runner.py \
    && chmod 0700 /runner-jobs \
    && chmod 0755 /workspaces \
    && chmod 0644 /runner/runner.py

ENV HOME=/root \
    CI=true \
    NO_COLOR=1 \
    FORCE_COLOR=0 \
    OPENCLAW_SKIP_CHANNELS=1 \
    CLAWDBOT_SKIP_CHANNELS=1

ENTRYPOINT ["dumb-init", "--"]
CMD ["python3", "/runner/runner.py"]
