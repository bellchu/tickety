# Tickety Helm chart

This chart installs the Tickety frontend, API, singleton worker, migration Job,
and an optional pgvector-enabled PostgreSQL StatefulSet. It supports Kubernetes
1.25 or later with Helm 3.13+ or Helm 4, and works with a standard ingress
controller or `LoadBalancer` Service.

## Install

The repository installer builds immutable application images, pushes them to
your registry, waits for migrations and workloads, then runs the chart's health
test:

```sh
./deploy.sh kubernetes \
  --registry registry.example.com/your-team/tickety
```

For direct Helm use, publish the backend and frontend Dockerfile targets first,
then set their repositories and tags:

```sh
helm upgrade --install tickety ./deploy/helm/tickety \
  --namespace tickety --create-namespace \
  --set-string backend.image.repository=registry.example.com/tickety/backend \
  --set-string backend.image.tag=2026-07-28 \
  --set-string frontend.image.repository=registry.example.com/tickety/frontend \
  --set-string frontend.image.tag=2026-07-28 \
  --wait --wait-for-jobs --timeout 10m

helm test tickety --namespace tickety
```

The default is evaluation-oriented demo mode, a private `ClusterIP` frontend,
and an 8 Gi persistent PostgreSQL volume. Use `kubectl port-forward -n tickety
service/tickety-frontend 3000:80` to reach that default installation.

## Configuration

See `values.yaml` for every setting and
`deploy/examples/production-values.yaml` for a secure production baseline.
Important groups are:

- `backend.image` and `frontend.image`: registry repository, immutable tag, and
  pull policy.
- `config`: runtime mode, public origin, CORS, login, and cookie controls.
- `secrets`: provider, webhook, SSO, and ITSM credentials stored in the
  chart-managed Secret.
- `existingSecret`: use a secret manager-provisioned Secret instead. It must
  contain `DATABASE_URL` and, for bundled PostgreSQL, `POSTGRES_PASSWORD`.
- `postgresql`: bundled storage, storage class, or an external database URL.
- `ingress` and `frontend.service`: choose one public exposure mechanism.
- `networkPolicy`: public HTTPS egress plus narrowly scoped exceptions for
  private database, AI, or ITSM endpoints.
- `backup`: optional custom-format PostgreSQL backups on a dedicated PVC, with
  archive validation, overlap prevention, and age-based retention. This
  currently requires the bundled PostgreSQL instance.

When the chart owns the Secret and bundled PostgreSQL, it generates an
alphanumeric database password on first install and reuses it on upgrades.
Changing that password later requires a coordinated PostgreSQL role-password
rotation; changing only the Helm value is intentionally not a rotation method.

When `backup.enabled=true`, the CronJob writes mode-restricted custom-format
dumps to its backup PVC and validates each archive with `pg_restore --list`
before publishing it. A valid archive is still not a disaster-recovery test:
regularly restore a dump into an isolated PostgreSQL instance and verify the
application against it.

For production, first create a real administrator while running the default
demo installation, then apply production values. This follows Tickety's
fail-closed identity transition: production startup disables the fixed demo
accounts and does not bootstrap a privileged user.

Before uninstalling a release that uses bundled PostgreSQL, retain the current
database password in a secret manager alongside the database backup. Helm
removes the chart-managed Secret but Kubernetes retains StatefulSet PVCs; a
later installation must reuse the original password to connect to that data.
