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

For Kubernetes, first create `tickety-secrets` as described in
[`k8s/README.md`](../k8s/README.md). The deployment workflow replaces and waits
for the hardened `k8s/migrate.yaml` Job before rolling the API, worker, or
frontend. A failed migration stops the rollout.

Revision `0001` is a frozen baseline. It creates a fresh database, or safely
adopts an unversioned database from the former `create_all` lifecycle only
after verifying that every baseline table and column exists. Partial or
unrecognised schemas fail closed. Revision `0002` idempotently adds the managed
ticket, portal capability, authentication, knowledge-governance, and service
workflow fields, indexes, defaults, and foreign keys while preserving rows.
Revision `0003` adds AI artifact provenance, cross-process claim state, and
durable request-budget tables without rewriting existing generated content.
Revision `0004` adds expiring provider-concurrency leases shared by API and
worker processes.

## Change procedure

1. Add a new revision; never edit a revision that has reached a shared
   environment.
2. Exercise `alembic upgrade head` against both an empty database and a copy of
   the previous schema.
3. Run `alembic check` to ensure SQLAlchemy metadata has no unmanaged drift.
4. Take and verify a database backup before applying the migration.
5. Apply the migration once, then roll application workloads and verify
   `/health/ready` plus the critical requester and agent workflows.

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
