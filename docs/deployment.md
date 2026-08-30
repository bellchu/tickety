# Deploying Tickety

Tickety has a local Docker Compose mode, an isolated MicroK8s development path,
and one production path on the OCI Kubernetes environment.

Each production installation must explicitly select:

- public origin: the `--host` argument
- Kubernetes namespace: `tickety`
- Helm release: `tickety`
- chart: [`deploy/helm/tickety`](../deploy/helm/tickety)
- release command: `./deploy.sh kubernetes`
- production gate: `scripts/verify-production-target.sh`

Do not use a direct frontend port, local Compose result, or unselected
Kubernetes context as production evidence.

## Local Docker Compose

Docker Compose is the quickest way to evaluate Tickety locally. It uses a
private PostgreSQL service, a migration job, the FastAPI backend, one worker,
and the Next.js frontend:

```sh
./deploy.sh docker
```

The frontend is published on the IPv4-loopback port selected by `TICKETY_PORT`
(3000 by default). Local/demo mode must not be exposed as production. Stop it
while retaining data with:

```sh
docker compose down
```

Use `docker compose down --volumes` only when intentionally discarding the
local database.

## Development on MicroK8s

The `dev` branch has its own MicroK8s release path. It builds the committed
`origin/dev` object and publishes through:

- SSH target: locally configured `TICKETY_DEV_SSH_*` values
- runtime: the existing MicroK8s `tickety` namespace
- public dev origin: locally configured `TICKETY_DEV_PUBLIC_HOST`
- release command: `scripts/deploy-dev-microk8s.sh`

Validate the local release artifacts before deploying:

```sh
scripts/validate-dev-deployment.sh
scripts/deploy-dev-microk8s.sh
```

This path is not production evidence and does not select or modify the OCI
production Kubernetes context.

## OCI production configuration

The production values baseline is
[`deploy/examples/production-values.yaml`](../deploy/examples/production-values.yaml).
It fixes the HTTPS origin, TLS ingress host, production mode, secure cookies,
and persistent PostgreSQL storage. Keep real credentials outside Git and use
`existingSecret` or an external Secret manager.

Select the OCI Kubernetes context and verify it before releasing. The installer
uses the current `kubectl` context and never invents a context name:

```sh
kubectl config current-context
kubectl cluster-info
```

Build and deploy with a registry prefix containing the `backend` and
`frontend` repositories:

```sh
./deploy.sh kubernetes \
  --host tickety.situ.io \
  --registry registry.example.com/tickety \
  --values deploy/examples/production-values.yaml \
  --platform linux/arm64 \
  --namespace tickety \
  --release tickety
```

The command:

1. validates the Kubernetes names, registry, and Helm chart;
2. builds and pushes immutable `linux/arm64` backend and frontend images for
   the selected OCI environment;
3. runs the migration Job and waits for the release workloads;
4. runs the Helm test;
5. proves that the active ingress, frontend build, static assets, and
   the configured public readiness endpoint belongs to the selected release.

Use `--skip-build --tag TAG` only when both immutable images already exist in
the registry. Do not place database URLs, provider keys, SSO secrets, registry
tokens, or private keys in the values file.

## Verification

Run the offline deployment checks before committing deployment changes:

```sh
scripts/validate-deployment.sh
scripts/verify-production-target.sh --self-test
```

For a live release, the target gate requires a single ingress for
the explicit production host, a ready non-terminating frontend Pod using the active image,
matching internal/public hashed assets, and a public readiness response with
`status=ready`. Run it with the selected namespace:

```sh
scripts/verify-production-target.sh --host tickety.situ.io --namespace tickety
kubectl get pods,jobs,service,ingress --namespace tickety
helm test tickety --namespace tickety --timeout 2m
```

Only evidence from the explicitly selected HTTPS production host counts as
production evidence.

## Upgrade and recovery

Migrations are forward-only. Before an upgrade that changes schema or data,
take and verify a PostgreSQL backup and record the current Git SHA and Alembic
revision. Keep the previous image tags and a matching database backup for
rollback.

If a migration fails, do not stamp it manually. Keep the previous healthy
release where compatibility permits, repair the migration or data, and rerun
the same Helm path. An application rollback is safe only when the previous
image is compatible with the migrated schema.

To remove the Helm release while retaining the bundled PostgreSQL volume:

```sh
helm uninstall tickety --namespace tickety
```

Delete persistent storage only after a verified backup and an explicit
decision to destroy the data.
