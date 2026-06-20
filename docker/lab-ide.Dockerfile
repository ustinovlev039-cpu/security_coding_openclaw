FROM node:24-bookworm

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    bash \
    curl \
    git \
    ca-certificates \
    ripgrep \
    dumb-init \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://code-server.dev/install.sh | sh

RUN corepack enable

WORKDIR /workspace

EXPOSE 8080

ENTRYPOINT ["dumb-init", "--"]

CMD ["code-server", "--bind-addr", "0.0.0.0:8080", "--auth", "password", "/workspace"]