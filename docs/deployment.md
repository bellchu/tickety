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
  --host tickety.example.com \
  --registry registry.example.com/tickety \
  --values deploy/examples/production-values.yaml \
  --platform linux/arm64 \
  --namespace tickety \
  --release tickety
```

The command:

1. validates the Kubernetes names, registry, and Helm chart;
2. builds and pushes `linux/arm64` backend and frontend images for the selected
   OCI environment, captures the manifest digests emitted by Buildx, and
   renders every application workload as `repository@sha256:…` (the pushed tag
   is not the deployed identity);
3. on an upgrade, drains the current API Deployment and confirms all old API
   Pods have exited, then runs the migration Job and starts the new release
   workloads;
4. runs the Helm test;
5. proves that the active ingress, frontend build, static assets, and
   the configured public readiness endpoint belongs to the selected release.

Use `--skip-build --backend-digest sha256:… --frontend-digest sha256:…` only
when both images already exist in the registry. The installer rejects tag-only
production releases and confirms both exact references are readable from the
registry before draining an upgrade; record the two registry digests with the
release evidence. When using the bundled PostgreSQL StatefulSet, also pass
`--postgresql-digest sha256:…`; its database Pod and backup CronJob are pinned
by the same production policy. This option is unnecessary with
`postgresql.enabled=false`. `--tag` is only a build transport tag and is
rejected with `--skip-build`.

For an external application Secret, the installer renders the effective Secret
name without reading Secret data, ensures the selected namespace exists, then
binds workload templates to that Secret's `metadata.resourceVersion`. A new
namespace is created before this read only when necessary for a first install;
the externally managed Secret itself must already be available there (or be
provisioned by its controller before the command continues). The installer
rechecks the resourceVersion after Helm tests and the public target gate, and
rejects a release if it changed.
Do not place database URLs, provider keys, SSO secrets, registry tokens, or
private keys in the values file.

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
scripts/verify-production-target.sh --host tickety.example.com --namespace tickety
kubectl get pods,jobs,service,ingress --namespace tickety
helm test tickety --namespace tickety --timeout 2m
```

Only evidence from the explicitly selected HTTPS production host counts as
production evidence.

## Upgrade and recovery

Migrations are forward-only. Before an upgrade that changes schema or data,
take and verify a PostgreSQL backup and record the current Git SHA and Alembic
revision. Keep the previous image tags and a matching database backup for an
explicit recovery decision; an image rollback alone does not restore schema.

Use `./deploy.sh kubernetes` for upgrades. It creates a short, intentional
application maintenance window: it scales the existing backend Deployment and,
when enabled, worker Deployment to zero, confirms all of their Pods are gone,
then permits the migration Job and new rollout. This prevents old API binaries
or scheduled workers from writing or consuming state across an authentication
schema cutover. Migration `0056` deliberately invalidates all existing browser
sessions and in-progress SSO authorization states; plan for every user to
authenticate again. Do not use a direct `helm upgrade` for that cutover unless
an equivalent auditable procedure drains every old chart-managed
database-writing Pod before migration, quiesces any external database writer,
and starts only new binaries afterward.

Upgrades that include persisted-settings encryption also run a read-only
preflight before `alembic upgrade head`. It refuses legacy plaintext or an
unreadable sensitive ciphertext while the API remains deliberately drained;
repair the condition before retrying the same release path. For a
pre-encryption database, use the explicit, backed-up maintenance migration in
[settings secret encryption](settings-secret-encryption.md) with the new image
and deployment keyring; confirm its count-only result before retrying the Helm
upgrade.

Attachment target provenance is endpoint-bound. Before changing an Azure Blob
endpoint, account, or container, drain or explicitly reconcile existing
attachments while the original target is still available. Older rows that only
recorded an account name deliberately fail closed after this upgrade: Tickety
will not read or delete a same-named blob at a replacement endpoint. Treat
those rows as a data-migration item rather than editing their provenance or
pointing the deployment at a guessed target.

If a migration or its preflight fails after the drain, do not stamp it
manually or assume the old API or worker is still serving. The application
remains unavailable by design until an explicit recovery is complete. Inspect
the migration Job and workload events, repair the migration or data, and rerun
the same Helm path. Restore the old Deployment only after confirming the failed
migration did not commit and that its image remains schema-compatible; if it
did commit, apply a forward-compatible fix or restore the verified database
backup.

To remove the Helm release while retaining the bundled PostgreSQL volume and
any chart-created backup PVC:

```sh
helm uninstall tickety --namespace tickety
```

Helm retains both the StatefulSet volume and the chart-created backup PVC. Delete
either persistent store only after a verified backup and an explicit decision to
destroy the data; an externally supplied backup claim remains operator-owned.
