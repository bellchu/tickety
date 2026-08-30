<p align="center">
  <img src="app/frontend-next/public/brand/tickety-mark.svg" alt="Tickety OPS Tower mark" width="88">
</p>

<h1 align="center">Tickety OPS Tower</h1>

<p align="center">
  <strong>Self-hosted intelligence for IT service operations</strong><br>
  <sub>Read authoritative records. Keep derived intelligence local. Act with confidence.</sub>
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#ai-providers">AI providers</a> ·
  <a href="#deployment">Deployment</a> ·
  <a href="#security">Security</a>
</p>

> **Read-only by default.** Tickety imports authoritative records, keeps
> analytics locally, and does not write ticket changes back to the source
> system.

## At a glance

| Product | Stack | Runtime |
| --- | --- | --- |
| IT service operations intelligence | FastAPI · Next.js · React · TypeScript | Docker Compose · Helm/Kubernetes |

| Data boundary | Production | Local evaluation |
| --- | --- | --- |
| ITSM source | Freshservice read-only sidecar | Standalone local ticket store |
| AI | Explicitly configured and opt-in | Disabled by default |
| Data state | Empty on first install | Empty on first install |

The backend uses Python 3.11, FastAPI, SQLAlchemy, Alembic, and PostgreSQL. The
frontend uses Next.js 16, React 19, and TypeScript. Deployment options include
Docker Compose and Kubernetes with Helm.

<details>
<summary><strong>Contents</strong></summary>

- [How Tickety works](#how-tickety-works)
- [Product areas](#product-areas)
- [Clean-install policy](#clean-install-policy)
- [Quick start](#quick-start)
- [Configuration at a glance](#configuration-at-a-glance)
- [AI providers](#ai-providers)
- [Development](#development)
- [Deployment](#deployment)
- [Security](#security)
- [License](#license)

</details>

## How Tickety works

Tickety keeps the system of record and the intelligence layer separate:

| Stage | What happens |
| --- | --- |
| 1. Import | The sync worker reads permitted records from the configured ITSM source. |
| 2. Project | Tickety stores a local, queryable projection with source metadata and audit history. |
| 3. Understand | Reports, SLA monitoring, related-ticket search, and optional AI analysis operate on local data. |
| 4. Work | Agents use one workspace for queues, follow-up, knowledge, routing, and operational decisions. |

This separation makes the deployment useful for analysis without turning an AI
or analytics feature into an implicit write path to the source system.

## Product areas

| Area | Purpose |
| --- | --- |
| Agent workspace | Work personal or team queues, inspect assignment context, and focus follow-up. |
| Tickets | Review details, comments, attachments, related records, audit history, and intelligence. |
| Reports | Explore volume, categories, status, resolution time, and SLA performance; export CSV evidence. |
| Intelligence | Surface attention queues, SLA risk, workload, trends, systemic issues, and routing recommendations. |
| Knowledge and catalog | Govern knowledge articles and publish services for consistent request intake. |
| Operations | Manage assets, problems, changes, surveys, email, and external-user directory data. |

AI features are assistive: triage, summaries, routes, resolution suggestions,
and systemic findings remain subject to the application's authorization and
review controls.

## Clean-install policy

A fresh installation is empty: Tickety does not create sample users, default
passwords, tickets, assets, knowledge articles, or other demonstration records.
Create the first administrator through your reviewed identity/bootstrap process
before exposing the service. Keep credentials in an ignored `.env`, an external
secret manager, or an existing Kubernetes Secret.

## Quick start

The Compose stack runs PostgreSQL, a migration job, the FastAPI API, a
background worker, and the Next.js frontend. It publishes the frontend only on
the local machine by default.

### Choose a runtime mode

| Mode | Intended use | ITSM source | Authentication |
| --- | --- | --- | --- |
| demo | Isolated local evaluation | Standalone local ticket store | Set LOGIN_REQUIRED=true for an explicit session |
| production | Shared or production-shaped deployment | Read-only Freshservice sidecar | Explicit session is always required |

The checked-in environment template uses production as the safe default. For
local feature evaluation, set APP_MODE=demo, LOGIN_REQUIRED=true, and
ITSM_PROVIDER=standalone before starting the stack. Never expose demo mode as a
production service.

At minimum, local Compose needs a database password and a matching connection
URL:

    POSTGRES_PASSWORD=replace-with-a-long-local-password
    DATABASE_URL=postgresql+psycopg2://tickety:replace-with-a-long-local-password@postgres:5432/tickety

Use a URL-safe password, or URL-encode reserved characters in the connection
URL. Keep all real credentials in the ignored environment file or a secret
manager.

1. Copy `.env.example` to `.env`.
2. Set a strong `POSTGRES_PASSWORD` and a matching `DATABASE_URL`.
3. Review `APP_MODE`, `LOGIN_REQUIRED`, `FRONTEND_URL`, and
   `CORS_ALLOW_ORIGINS` for your environment.
4. Start the stack:

```bash
./deploy.sh docker
```

The frontend is available at `http://localhost:3000`. No account or application
data is created automatically. After migrations finish, create the first
administrator interactively from a trusted terminal:

```bash
docker compose run --rm backend \
  python -m app.backend.bootstrap_admin \
  --name "Project Owner" \
  --email owner@example.com
```

The command accepts a password only through a hidden prompt and refuses to run
after any user exists.

## Configuration at a glance

The full reference is in [.env.example](.env.example). These are the settings
most deployments should review first:

| Concern | Settings | Guidance |
| --- | --- | --- |
| Runtime mode | APP_MODE, LOGIN_REQUIRED | Use demo only on isolated infrastructure; production always requires an explicit session. |
| Database | POSTGRES_PASSWORD, DATABASE_URL | Use the same password in both values and URL-encode reserved characters. |
| Browser boundary | FRONTEND_URL, CORS_ALLOW_ORIGINS, TRUSTED_HOSTS | Set exact public origins and backend hostnames; do not use a wildcard in shared environments. |
| ITSM source | ITSM_PROVIDER, Freshservice settings | Demo can use standalone; production is constrained to the read-only Freshservice sidecar. |
| AI provider | DEFAULT_MODEL, FOUNDRY_* or CUSTOM_* | Configure one intended provider, restrict egress hosts, and keep secrets outside Git. |
| AI automation | AUTO_* and TICKET_RAG_* | Every automatic workflow and RAG v2 rollout flag is off until deliberately enabled. |
| Identity | SSO_ENABLED and provider-specific SSO settings | Use the [SSO guide](docs/sso.md) for Entra ID, Okta, or generic OIDC. |

## AI providers

Tickety supports Microsoft Foundry through its OpenAI-compatible v1 endpoint and
one generic OpenAI-compatible custom endpoint. Configure only the provider you
intend to use:

AI is an optional processing plane, separate from ITSM synchronization:

| Capability | Default | Operational note |
| --- | --- | --- |
| On-demand ticket analysis | Available after provider setup | Requires an authenticated user and local policy checks. |
| Automatic triage, summaries, routing, resolution, and systemic analysis | Off | Enable each workflow deliberately; background jobs remain budgeted and observable. |
| Ticket embeddings and RAG v2 | Off | Requires pgvector and a staged rollout; lexical retrieval remains the rollback path. |

```bash
FOUNDRY_API_BASE=https://<resource>.services.ai.azure.com/openai/v1
FOUNDRY_AUTH_METHOD=api_key
FOUNDRY_API_KEY=<secret>
DEFAULT_MODEL=foundry/<deployment-name>
```

Provider URLs, egress allowlists, authentication, request budgets, and automatic
analysis are fail-closed in production. Ticket text and retrieved content are
treated as untrusted input. Resolver routing is advisory and uses only the
closed resolver taxonomy configured by this project.

## Development

Backend tests:

```bash
APP_MODE=demo DATABASE_URL=sqlite:// PYTHONPATH=. \
  python -m unittest discover -s tests -p 'test_*.py' -v
```

This uses the same isolated SQLite test mode as the repository CI. For
PostgreSQL-backed retrieval tests, use the dedicated pgvector service described
in the CI workflow.

Frontend checks:

```bash
cd app/frontend-next
npm ci
npm test
npm run lint
npm run typecheck
npm run build
```

Deployment validation:

```bash
scripts/validate-deployment.sh
scripts/validate-dev-deployment.sh
```

## Deployment

| Path | Best for | Guide |
| --- | --- | --- |
| Docker Compose | Local evaluation and isolated development | [Deployment guide](docs/deployment.md#local-docker-compose) |
| MicroK8s | Development release on the dedicated dev path | [Development MicroK8s guide](docs/dev-deployment.md) |
| Helm/Kubernetes | OCI production deployment with immutable images | [Deployment guide](docs/deployment.md#oci-production-configuration) |
| Schema lifecycle | Forward-only migrations and recovery | [Database migrations](docs/database-migrations.md) |
| Enterprise login | Microsoft Entra ID or Okta SSO | [SSO configuration](docs/sso.md) |
| Freshworks extension | Read-only Freshservice sidebar/full-page app | [Freshworks app guide](freshworks-app/README.md) |
| Retrieval rollout | Staged pgvector indexing, evaluation, and rollback | [RAG v2 operations guide](docs/rag-v2.md) |

Production deployments require an explicit public host and registry:

```bash
./deploy.sh kubernetes \
  --host tickety.situ.io \
  --registry registry.example.com/tickety \
  --platform linux/arm64 \
  --values deploy/examples/production-values.yaml
```

The development release script likewise reads its SSH destination and public
host from `TICKETY_DEV_*` environment variables. Environment-specific values
must not be committed.

## Security

- Never commit `.env` files, credentials, private keys, database dumps, or
  customer data.
- Use `LOGIN_REQUIRED=true`, secure cookies, exact CORS origins, and HTTPS for
  any shared environment.
- Keep automatic integrations and AI processing disabled until their data-flow,
  budgets, and provider destinations have been reviewed.
- Report vulnerabilities privately to the repository maintainers rather than
  opening a public issue containing exploit details.

## License

[MIT](LICENSE)
