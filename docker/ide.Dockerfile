FROM node:24-bookworm

ARG CODE_SERVER_VERSION=4.104.2
ARG CODE_SERVER_URL=https://github.com/coder/code-server/releases/download/v4.104.2/code-server-4.104.2-linux-amd64.tar.gz

RUN curl -fsSL "${CODE_SERVER_URL}" -o /tmp/code-server.tar.gz \
    && mkdir -p /opt/code-server \
    && tar -xzf /tmp/code-server.tar.gz --strip-components=1 -C /opt/code-server \
    && ln -s /opt/code-server/bin/code-server /usr/local/bin/code-server \
    && rm /tmp/code-server.tar.gz \
    && code-server --version \
    && groupadd --gid 10001 labuser \
    && useradd --uid 10001 --gid 10001 --create-home --home-dir /ide-data/home --shell /bin/bash labuser \
    && mkdir -p /ide-data/home /ide-data/user-data/User /ide-data/extensions /workspaces /deps/project/node_modules \
    && printf '%s\n' '{' \
      '  "telemetry.telemetryLevel": "off",' \
      '  "extensions.autoCheckUpdates": false,' \
      '  "extensions.autoUpdate": false,' \
      '  "workbench.startupEditor": "none",' \
      '  "security.workspace.trust.enabled": false' \
      '}' > /ide-data/user-data/User/settings.json \
    && chown -R labuser:labuser /ide-data /workspaces

ENV HOME=/ide-data/home \
    TMPDIR=/tmp \
    VSCODE_DISABLE_TELEMETRY=1 \
    DISABLE_TELEMETRY=1

USER labuser
WORKDIR /workspaces/default

EXPOSE 3000

CMD ["sh", "-lc", "while [ ! -f /workspaces/default/package.json ]; do sleep 0.2; done; exec code-server /workspaces/default --bind-addr 0.0.0.0:3000 --auth none --disable-telemetry --disable-update-check --user-data-dir /ide-data/user-data --extensions-dir /ide-data/extensions --app-name 'OpenClaw Security Lab — Ownerless Gateway'"]
