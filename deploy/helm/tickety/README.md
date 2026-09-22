# Tickety Helm chart

This chart installs the Tickety frontend, API, singleton worker, migration Job,
and an optional pgvector-enabled PostgreSQL StatefulSet. It supports Kubernetes
1.25 or later with Helm 3.14+ or Helm 4, and works with a standard ingress
controller or `LoadBalancer` Service.

## Install

The repository installer builds immutable application images, pushes them to
your registry, waits for migrations and workloads, then runs the chart's health
test:

```sh
./deploy.sh kubernetes \
  --registry registry.example.com/your-team/tickety
```

For direct production Helm use, begin with
`deploy/examples/production-values.yaml`, replace its public hostname and all
three digest placeholders (backend, frontend, and bundled PostgreSQL), then
publish the backend and frontend Dockerfile targets. The command below layers
the resulting production configuration with the final repositories, build tags,
and registry manifest digests:

```sh
EXTERNAL_SECRET_RESOURCE_VERSION="$(kubectl get secret tickety-runtime-secrets \
  --namespace tickety --output=jsonpath='{.metadata.resourceVersion}')"

helm upgrade --install tickety ./deploy/helm/tickety \
  --namespace tickety --create-namespace \
  --values deploy/examples/production-values.yaml \
  --set-string backend.image.repository=registry.example.com/tickety/backend \
  --set-string backend.image.tag=2026-07-28 \
  --set-string backend.image.digest=sha256:REPLACE_WITH_64_LOWERCASE_HEX_CHARACTERS \
  --set-string frontend.image.repository=registry.example.com/tickety/frontend \
  --set-string frontend.image.tag=2026-07-28 \
  --set-string frontend.image.digest=sha256:REPLACE_WITH_64_LOWERCASE_HEX_CHARACTERS \
  --set-string postgresql.image.digest=sha256:REPLACE_WITH_64_LOWERCASE_HEX_CHARACTERS \
  --set imageDigestPolicy.requireDigests=true \
  --set-string existingSecret=tickety-runtime-secrets \
  --set-string existingSecretRolloutToken="$EXTERNAL_SECRET_RESOURCE_VERSION" \
  --wait --wait-for-jobs --timeout 10m

helm test tickety --namespace tickety
```

`deploy.sh kubernetes` resolves this non-secret token from the effective
external Secret automatically. Direct Helm users must read the Secret metadata
the same way immediately before the release, then verify it did not rotate
during the rollout.

The default is evaluation-oriented demo mode, a private `ClusterIP` frontend,
and an 8 Gi persistent PostgreSQL volume. Use `kubectl port-forward -n tickety
service/tickety-frontend 3000:80` to reach that default installation.

## Configuration

See `values.yaml` for every setting and
`deploy/examples/production-values.yaml` for a secure production baseline.
Important groups are:

- `backend.image` and `frontend.image`: registry repository, build tag,
  manifest digest, and pull policy. The chart rejects `latest` (including case
  variants). `imageDigestPolicy.requireDigests=true` makes rendering fail unless
  both application images use lowercase `sha256:` manifest digests, and Pods
  receive `repository@digest` rather than a tag. Its `dev` defaults are
  evaluation-only. `./deploy.sh kubernetes` obtains both pushed digests from
  Buildx metadata; `--skip-build` requires explicit backend and frontend
  digests.
- The production baseline runs two frontend and API replicas. The chart renders
  a `minAvailable: 1` PodDisruptionBudget for either workload only when its
  replica count is at least two; the singleton worker and PostgreSQL are
  intentionally excluded.
- `worker.shutdownDeadlineSeconds`: bounded cooperative shutdown budget for
  the singleton worker (5–30 seconds; default 20). SIGTERM first closes
  scheduler and RAG admission, then waits only within this budget. The worker
  Pod has a 45-second grace period, and incomplete durable sync/embedding
  leases are recovered by the next worker rather than force-cleared.
- `worker.image`: the worker uses the same repository, tag, and digest as the backend
  and migration Job. Repository, tag, or digest overrides that differ from
  `backend.image` fail chart rendering, preventing a worker rollout from
  running against an unverified schema contract.
- `config`: runtime mode, public origin, CORS, login, cookie controls, and the
  structured `config.sso` Entra ID/Okta/OIDC settings.
- `config.sessionStorageMode`: `auto` is the chart default. It resolves to
  `hashed` on a new Helm install and to `compat` on an upgrade, so old and new
  API Pods can share browser sessions during the rollout. After every prior
  API image is gone, set it explicitly to `hashed` in a second Helm upgrade,
  which stops raw writes. The new code retains a bounded raw-token lookup only
  until legacy rows reach their normal 14-day session expiry, so existing
  browser cookies are not needlessly invalidated; plan for that full window
  before treating the storage transition as complete. `compat` is available only as an
  explicit override. The application and `.env.example` default to `hashed`.
- `secrets`: provider, webhook, SSO, and ITSM credentials stored in the
  chart-managed Secret.
- `config.extra`: optional non-secret environment settings rendered into the
  ConfigMap. Reserved runtime names and credential-like names (including
  `*_KEY`, `*_SECRET`, `*_TOKEN`, password, connection-string, certificate,
  and settings-encryption names) fail schema/template validation. Put such
  values only in `secrets` or an externally managed `existingSecret`.
- `existingSecret`: use a secret manager-provisioned Secret instead. It must
  contain `DATABASE_URL`, `TICKETY_SETTINGS_ENCRYPTION_ACTIVE_KID`,
  `TICKETY_SETTINGS_ENCRYPTION_KEYS_JSON`, and, for bundled PostgreSQL,
  `POSTGRES_PASSWORD`. Helm cannot inspect externally managed Secret data at
  render time; the migration Job's strict preflight rejects missing or invalid
  keyring data before it changes the schema.
- `TICKETY_SETTINGS_ENCRYPTION_ACTIVE_KID` and
  `TICKETY_SETTINGS_ENCRYPTION_KEYS_JSON`: deployment-injected settings
  keyring values. They are required before the migration Job, an administrator,
  or OAuth refresh can persist a credential. If the chart manages its Secret,
  it rejects a render that omits either key. The JSON maps KIDs to
  base64-encoded 32-byte AES-256-GCM keys; keep the active and previous KIDs
  during rotation. For production, keep both values in an external Secret
  manager and select it with `existingSecret`; never place either value in Git
  or a committed Helm values file.
- `existingSecretRolloutToken`: a non-secret value to change after an external
  Secret rotation; production rendering refuses an empty value. `deploy.sh`
  renders the effective external Secret name, reads only its Kubernetes
  `metadata.resourceVersion`, puts that value on every workload template, and
  verifies it did not change during deployment. Direct Helm operations must
  provide the same non-secret resourceVersion token themselves.
- `postgresql`: bundled storage, storage class, or an external database URL.
  When production digest policy is enabled and bundled PostgreSQL is rendered,
  `postgresql.image.digest` is mandatory; the StatefulSet and backup CronJob
  both use `repository@digest`. `deploy.sh` takes its final resolved reference
  from the chart's non-secret rendered metadata and registry-verifies it before
  draining an upgrade. It is intentionally out of scope when
  `postgresql.enabled=false` because this chart then runs no PostgreSQL image.
- `ingress` and `frontend.service`: choose one public exposure mechanism.
- `networkPolicy`: frontend-only ingress to the backend API, public HTTPS
  egress, plus narrowly scoped exceptions for private database, AI, or ITSM
  endpoints. Public ingress reaches the frontend Service, never the backend
  Service directly.
- `config.notificationOutbox*`: non-secret limits for the database-backed
  realtime outbox. Every API replica independently polls it and fans events
  out only to its local authenticated WebSocket clients. A transactionally
  locked dispatch order, rather than a PostgreSQL sequence value, prevents
  concurrent commits from creating skipped cursor gaps; dispatchers also
  perform configurable multi-batch expiry cleanup and fail readiness while a
  live dispatcher is stale, so `worker.enabled=false` remains supported.
- `backup`: optional custom-format PostgreSQL backups on a dedicated PVC, with
  archive validation, overlap prevention, and age-based retention. This
  currently requires the bundled PostgreSQL instance. Its Pod is egress
  restricted to cluster DNS and that PostgreSQL Service.
- `backend.topologySpread` and `frontend.topologySpread`: optional per-workload
  topology constraints. The production baseline enables hostname spreading for
  the two public API and proxy replicas; use a multi-zone external database for
  database failover, because the bundled PostgreSQL StatefulSet is single-node.

For SSO, set `config.sso.provider` to `entra` or `okta`, put the client ID and
tenant/domain in `config.sso`, and store `SSO_CLIENT_SECRET` in `secrets` or the
Secret named by `existingSecret`. The callback is derived from
`config.frontendUrl`. See the [SSO setup
guide](../../../docs/sso.md) for complete provider configuration and examples.

When the chart owns the Secret and bundled PostgreSQL, it generates an
alphanumeric database password on first install and reuses it on upgrades.
Changing that password later requires a coordinated PostgreSQL role-password
rotation; changing only the Helm value is intentionally not a rotation method.

Kubernetes does not restart containers when an `envFrom` Secret changes. When
using `existingSecret`, rotate it through the secret manager, then change
`existingSecretRolloutToken` in the Helm values (for example, to a rotation
timestamp or secret-manager version) and run `helm upgrade`. This changes only
the Pod-template annotation; the chart never reads or hashes the external
Secret.

When `backup.enabled=true`, the CronJob writes mode-restricted custom-format
dumps to its backup PVC and validates each archive with `pg_restore --list`
before publishing it. A valid archive is still not a disaster-recovery test:
regularly restore a dump into an isolated PostgreSQL instance and verify the
application against it. The chart's backup PVC is in-cluster storage, so a
production disaster-recovery plan also needs independently retained backups
and restore evidence outside the cluster. When the chart creates that claim
(rather than using `backup.persistence.existingClaim`), it marks the PVC with
`helm.sh/resource-policy: keep`: Helm retains it if the release is uninstalled
or backups are later disabled. Delete that claim manually only after a verified
backup and an explicit data-destruction decision.

For production, first create a real administrator while running the default
demo installation, then apply production values. This follows Tickety's
fail-closed identity transition: production startup disables the fixed demo
accounts and does not bootstrap a privileged user.

Before uninstalling a release that uses bundled PostgreSQL, retain the current
database password in a secret manager alongside the database backup. Helm
removes the chart-managed Secret but Kubernetes retains StatefulSet PVCs and a
chart-created backup PVC; a later installation must reuse the original password
to connect to that data and should deliberately choose whether to reuse or
remove the retained backup claim.

## Upgrade recovery

`./deploy.sh kubernetes` detects an existing Helm release before applying it.
It deliberately does not use `--atomic`. It uses
`--reset-then-reuse-values` for an existing release: new chart defaults are
layered with the release's existing values before the current command's image,
origin, and optional values-file overrides. This retains external database and
Secret ownership instead of silently falling back to chart defaults. Database migrations run forward with
`alembic upgrade head`, and production verifies the exact Alembic head. Once a
migration has advanced the database, restoring the previous Kubernetes release
would not restore a compatible application or downgrade the schema. A failed
upgrade is therefore retained for inspection and explicit recovery rather than
claiming an automatic old-image rollback.

Before every existing-release upgrade, the installer scales the current backend
Deployment and, when enabled, worker Deployment to zero and waits until every
matching Pod has exited. It then runs the migration Job and starts only new
binaries. This is an intentional, brief application maintenance window that
prevents old API binaries or scheduled workers from overlapping an
authentication schema cutover. In particular, migration `0056` invalidates all
existing browser sessions and in-progress SSO authorization states, so users
must authenticate again after that upgrade. Do not replace this sequence with a
direct `helm upgrade`; any equivalent operational procedure must drain every
old chart-managed database-writing Pod before migration, quiesce any external
database writer, and start new binaries only afterward.

For a failed upgrade, inspect the migration Job and workload events, then build
and deploy a forward-compatible fix against the current schema. If recovery
requires returning the data to an earlier state, restore a verified database
backup using the documented database-recovery procedure before deploying a
compatible release. Do not treat `helm rollback` as schema recovery unless the
target image has been explicitly verified against the already-migrated schema.

A first install also does not use atomic cleanup: its StatefulSet PVC and
diagnostic resources remain available for a safe retry instead of risking data
loss.
