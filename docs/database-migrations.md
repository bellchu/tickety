# Database migrations

Tickety uses Alembic as the only production schema authority. Application
pods verify that the database is at the repository's migration head and exit
without running `create_all` or ad-hoc DDL when `APP_MODE=production`.

## Running migrations

Set `DATABASE_URL` through the deployment secret, then run:

```sh
alembic current
alembic upgrade head
alembic check
```

For supported Kubernetes and AKS deployments, use
[`deploy/helm/tickety`](../deploy/helm/tickety) through
[`deploy.sh`](../deploy.sh). Each Helm revision creates a migration Job, and
the deployment waits for Jobs to complete. Backend and worker Pods also wait
until the database is at the Alembic head, so they cannot become ready against
an old schema. A failed migration causes the Helm deployment to fail. See the
[deployment guide](deployment.md) for the command and values-file workflow.

The raw manifests in [`k8s/`](../k8s) are a legacy local-cluster workflow.
Their `k8s/migrate.yaml` Job can still be run manually, but it is not the
supported generic Kubernetes or AKS path. Do not run a raw-manifest migration
Job in the namespace of a Helm-managed release.

Revision `0001` is a frozen baseline. It creates a fresh database, or safely
adopts an unversioned database from the former `create_all` lifecycle only
after verifying that every baseline table and column exists. Partial or
unrecognised schemas fail closed. Revision `0002` idempotently adds the managed
ticket, portal capability, authentication, knowledge-governance, and service
workflow fields, indexes, defaults, and foreign keys while preserving rows.
Revision `0003` adds AI artifact provenance, cross-process claim state, and
durable request-budget tables without rewriting existing generated content.
Revision `0004` adds expiring provider-concurrency leases shared by API and
worker processes. Revision `0005` separates AI-suggested categories from the
canonical human-managed ticket category and adds the PostgreSQL full-text
search index without overwriting later human category decisions.

## Change procedure

1. Add a new revision; never edit a revision that has reached a shared
   environment.
2. Exercise `alembic upgrade head` against both an empty database and a copy of
   the previous schema.
3. Run `alembic check` to ensure SQLAlchemy metadata has no unmanaged drift.
4. Take and verify a database backup before applying the migration.
5. Deploy through Helm, which applies and waits for the migration Job before
   workloads become ready. Verify the frontend-proxied `/api/health/ready`
   endpoint plus the critical requester and agent workflows.

## Forward-only and recovery policy

Migrations are forward-only. The included revisions intentionally refuse
`alembic downgrade` because dropping columns or rebuilding tables can destroy
production data. Roll back application images only when the prior version is
compatible with the upgraded schema. Otherwise, stop writes and choose one of:

- apply a reviewed forward-fix revision; or
- restore the pre-migration backup into a clean database and repoint workloads.

For PostgreSQL, use the organisation's managed snapshot process or a
consistent `pg_dump` custom-format backup. Record the migration revision with
the backup, encrypt and restrict access to it, define retention, and regularly
test restoration. A backup is not considered valid until a restore has been
verified.
