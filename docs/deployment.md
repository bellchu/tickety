# Deploying Tickety OPS Tower

Tickety OPS Tower has one production environment and one supported production release
path:

- public origin: `https://tickety.nexora.com`
- Cloudflare Tunnel origin: `https://localhost:443`
- Compose proxy: `tunnel-proxy`
- application target: `frontend:3000`
- co-resident administrative ingress: `ticketyssh.nexora.com -> ssh://localhost:22`
- release command: `./deploy.sh docker`

Do not use another hostname, a direct frontend port, Kubernetes, Helm, or a
different tunnel as production evidence. If the Compose topology, the applied
Cloudflare configuration, or the public build evidence disagree, stop the
release and resolve the conflict before changing infrastructure.
`ticketyssh.nexora.com` is an auxiliary SSH route on the same host and tunnel;
it is never application readiness, version, monitoring, or deployment evidence.

## Local demo

Docker Compose uses private PostgreSQL, a persistent named volume, a migration
job, the FastAPI backend, one worker, and the Next.js frontend. Install Docker
Engine or Docker Desktop with Docker Compose 2.24 or later.

```sh
docker compose up --build --wait
```

The demo frontend is available on the IPv4-loopback port selected by
`TICKETY_PORT` (3000 by default). Demo mode contains seeded identities and must
not be exposed as production. Stop it while retaining data with:

```sh
docker compose down
```

`docker compose down --volumes` permanently removes the Compose PostgreSQL
volume. Use it only when intentionally discarding demo data or after retaining
a verified backup.

## Production configuration

Copy `.env.example` to the ignored `.env` file and review at least these
values:

```dotenv
APP_MODE=production
TICKETY_DEPLOYMENT_CLASS=production
LOGIN_REQUIRED=true
POSTGRES_USER=tickety
POSTGRES_PASSWORD=<unique-password>
POSTGRES_DB=tickety
DATABASE_URL=postgresql+psycopg2://tickety:<url-encoded-password>@postgres:5432/tickety
FRONTEND_URL=https://tickety.nexora.com
CORS_ALLOW_ORIGINS=https://tickety.nexora.com
COOKIE_SECURE=true
COOKIE_SAMESITE=lax
```

The username, password, and database in `DATABASE_URL` must match the three
`POSTGRES_*` values. URL-encode credentials that contain reserved characters.
Keep `.env`, database dumps, private keys, and integration credentials out of
the Git tree and Docker build context. Configure only the ITSM, SSO, webhook,
LLM, embedding, or email integrations the installation uses.

Microsoft Entra ID and Okta callbacks are derived from `FRONTEND_URL`; follow
the SSO guide instead of inventing another callback origin.

### First administrator

A fresh production database intentionally has no seeded administrator. Perform
the one-time identity bootstrap in a private, controlled demo instance, create
a separate real administrator (or configure a reviewed SSO bootstrap), verify
that account, and then enable the production configuration. Demo credentials
must no longer work before public exposure.

For an existing Compose volume, rotate the database password inside PostgreSQL
before changing `.env`:

```sh
docker compose exec postgres \
  psql --username tickety --dbname tickety --command '\password tickety'
```

Changing `POSTGRES_USER`, `POSTGRES_PASSWORD`, or `POSTGRES_DB` alone does not
rewrite an initialized PostgreSQL volume. Keep the database role and
`DATABASE_URL` synchronized explicitly.

## Release

Before release, confirm the fixed, currently applied mapping without changing
infrastructure:

```sh
scripts/verify-compose-production.sh --mapping-only
```

The preflight proves that the active Cloudflare process has exactly the ordered
`tickety.nexora.com -> https://localhost:443` web ingress with
`originRequest.noTLSVerify=true`, the co-resident
`ticketyssh.nexora.com -> ssh://localhost:22` administrative ingress, and the
unscoped 404 fallback. It also proves that Compose binds TCP 443 on IPv4
loopback and that `tunnel-proxy` forwards to `frontend:3000`. It rejects
`DOCKER_HOST`/`DOCKER_CONTEXT` overrides,
requires the active Docker context to resolve to
`unix:///var/run/docker.sock`, and pins every build, rollout, and verification
command to that local socket.

Commit the exact source to deploy and require a clean worktree. Then run:

```sh
./deploy.sh docker
```

The command:

1. rejects a dirty or unauditable Git worktree;
2. verifies the fixed mapping before the build;
3. builds every Compose image with the current 12-character Git SHA and UTC
   build time;
4. rejects a source change during the build;
5. verifies the mapping again before rollout;
6. runs Alembic to head and waits for every long-running service to become
   healthy;
7. verifies the expected build through both the local tunnel origin and
   `https://tickety.nexora.com`;
8. compares every public Next.js static asset with the running frontend image.

No alternate deployment mode is accepted by `deploy.sh`.

## Post-release verification

Rerun the full verifier with the committed build:

```sh
FULL_SHA=$(git rev-parse HEAD)
SHORT_SHA=$(git rev-parse --short=12 HEAD)
scripts/verify-compose-production.sh \
  --expected-full-sha "$FULL_SHA" \
  --expected-short-sha "$SHORT_SHA"
```

Retain the command output as release evidence. It includes:

- the full and short source SHA and a clean-worktree result;
- applied Compose configuration hashes;
- healthy backend, worker, frontend, PostgreSQL, and tunnel-proxy containers;
- a successful migration container exit;
- backend image SHA/time metadata;
- local and public readiness JSON;
- public version JSON with the expected build SHA;
- frontend BUILD_ID and static-asset manifest hashes.

Only the readiness and version responses from
`https://tickety.nexora.com` count as public production verification.

## Upgrade and recovery

Migrations are forward-only. Before an upgrade that changes schema or data,
take a PostgreSQL backup, verify that it can be read, and record the current
Git SHA and Alembic revision. Review migration-specific preconditions before
running the release.

If a migration fails, do not stamp it manually. Keep the previous healthy
application available where schema compatibility permits, repair the data or
migration, and rerun the same audited Compose path.

An application-image rollback is safe only when the previous revision is
compatible with the migrated schema. Otherwise restore the verified database
backup and deploy its matching committed application revision. See the
database migration guide for the detailed recovery policy.

Never use another hostname's health response, a direct container port, or a
non-Compose workload as proof that production is ready.
