# Containerised reference deployment

A locked runtime for external pilots (issue #89): the image is built **from
the wheel** (the artifact the `wheel-contract` CI job proves fulfils the
CLI/API promise), never from an editable checkout, so a pilot runs exactly
what CI verified. Base images are pinned by digest; the container runs
non-root; the `container-contract` CI job builds this image and runs the
contract smoke *inside* it (`remora doctor --json`, `GET /v1/health`) on
every push.

## Build and run

```bash
docker build -f deploy/reference/Dockerfile -t remora-reference .
docker run --rm -p 8000:8000 remora-reference
curl -fsS http://localhost:8000/v1/health
```

The full pilot topology (API plus durable Postgres state, which the
production-durability gate requires) is the compose file:

```bash
docker compose -f deploy/reference/docker-compose.yml up --build
```

Production (`REMORA_ENV=production`) refuses to start without real signing
keys (`REMORA_PDP_SIGNING_KEY`, `REMORA_LEASE_SIGNING_KEY`,
`REMORA_ENVELOPE_SIGNING_KEY`) and a durable DSN; the compose placeholders
are for development only.

## Reproducibility

Two digests fix the runtime:

- **Base images** are pinned by digest in `deploy/reference/Dockerfile` and
  `docker-compose.yml`; a rebuild differs only if those files change.
- **The built image digest** for a pilot install is recorded in the release
  notes of the tagged release the image was built from (`docker inspect
  --format '{{index .RepoDigests 0}}'` after push, or the image ID for a
  local build). Recording it is part of the release checklist, so a pilot's
  runtime is reproducible byte-for-byte from the notes.

## What the in-image smoke proves

The `container-contract` job (ci.yml) runs, inside the built image:

1. `remora doctor --json`: the CLI entrypoint resolves from the installed
   wheel, with the checkout nowhere on `sys.path`;
2. the API serves and `GET /v1/health` answers 200;
3. the compose file parses (`docker compose config`).

A surface listed in `docs/assurance/shipped_surfaces_v1.yaml` is checked by
the named jobs on every push; this deployment is the `container-reference`
surface there.

→ [execution-quickstart.md](execution-quickstart.md) for the enforcing
`/v1/execution/*` flow once the container is up;
[onprem-airgapped.md](onprem-airgapped.md) for air-gapped installs.
