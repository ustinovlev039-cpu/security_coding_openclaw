# OpenClaw: Ownerless Gateway

Local single-user MVP for a Broken Access Control / Security Coding lab.

## Prerequisites

- Docker with Docker Compose.
- Node/npm only for local frontend checks.
- Python 3.12 only for local backend syntax checks.

## Clone / Setup

Clone this repository, then make sure `openclaw-training-fork/` exists before building the lab.

## OpenClaw Training Source

`openclaw-training-fork` is currently recorded by Git as a `160000` gitlink at commit `29dc65403faf41dc52944c02a0db9fa4b8457395`, but this repository has no `.gitmodules` entry. The local checkout contains a nested Git directory, so this is not a reproducible submodule setup.

Release blocker: a normal fresh clone cannot reconstruct `openclaw-training-fork` from repository metadata alone. Until that is fixed, provide the vulnerable OpenClaw training source manually at `openclaw-training-fork/` before running Docker Compose.

## Launch

```bash
docker compose -f docker-compose.lab.yml up -d --build
```

Frontend: http://127.0.0.1:5173  
Backend: http://127.0.0.1:8000  
Code OSS IDE: http://127.0.0.1:3000

Stage 4B adds a pinned Code OSS browser editor package: `code-server@4.104.2`. The version is pinned so local lab behavior does not drift with `latest`. Docker Hub confirms `gitpod/openvscode-server:1.103.1` exists, but this local environment cannot pull Docker Hub blobs over IPv6, so the MVP image builds from the already-used `node:24-bookworm` base and installs the pinned compatible Code OSS server package during image build.

Reset workspace:

```bash
curl -X POST http://127.0.0.1:8000/api/lab/reset
```

## Runner Isolation

The runner does not mount `.env`, user home, `.ssh`, git credentials, Docker socket, or arbitrary host paths. It runs with `network_mode: none`, read-only root filesystem, tmpfs `/tmp`, dropped capabilities, and fixed job types only.

The IDE container opens only the disposable participant workspace volume at `/workspaces/default` plus its own user-data volume. It does not mount the Docker socket, host home, `.ssh`, git credentials, runner jobs, hidden validation, backend source, frontend source, or the canonical `openclaw-training-fork` template.

This is a single-user local MVP. The default workspace is `.lab/workspaces/default` with workspace id `default`, and it is not suitable for concurrent multi-user deployment.

Release blocker: `openclaw-training-fork` must be supplied locally until a proper training fork, Git submodule, or versioned vendor snapshot is chosen.
