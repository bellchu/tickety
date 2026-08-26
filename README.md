<div align="center">
  <img src="https://img.shields.io/badge/python-3.11-blue" alt="Python 3.11">
  <img src="https://img.shields.io/badge/next.js-16.3-black" alt="Next.js 16.3">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT">
</div>

---

Tickety — a read-only AI sidekick for an existing ITSM system. Freshservice is the current system of record; Tickety imports tickets and agent data, stores intelligence locally, and never writes back.

## Screenshots

<p align="center">
  <img src="docs/screenshots/dashboard.png" width="48%" alt="Dashboard">
  <img src="docs/screenshots/tickets.png" width="48%" alt="Tickets">
  <img src="docs/screenshots/ticket-detail.png" width="48%" alt="Ticket Detail">
  <img src="docs/screenshots/services.png" width="48%" alt="Service Catalog">
  <img src="docs/screenshots/problems.png" width="48%" alt="Problem Management">
  <img src="docs/screenshots/changes.png" width="48%" alt="Change Management">
  <img src="docs/screenshots/assets.png" width="48%" alt="Asset Management">
  <img src="docs/screenshots/knowledge.png" width="48%" alt="Knowledge Base">
  <img src="docs/screenshots/reports.png" width="48%" alt="Reports">
  <img src="docs/screenshots/settings.png" width="48%" alt="Settings">
</p>

## Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.11 · FastAPI · SQLAlchemy · APScheduler |
| Frontend | Next.js 16.3 · Tailwind CSS · TanStack Query · Recharts |
| AI | LiteLLM (Microsoft Foundry · Custom OpenAI-compatible API) |
| Database | PostgreSQL |
| Infra | Docker Compose · Cloudflare Tunnel · Caddy |

## Quick start

Python dependencies are declared in `requirements.txt` and reproducibly pinned
in `requirements.lock`. CI and production images install the lock. After an
intentional dependency change, regenerate it with:

```bash
uv pip compile requirements.txt --universal --python-version 3.11 --output-file requirements.lock
```

```bash
docker compose up --build --wait
open http://localhost:3000
```

This starts the demo configuration, including PostgreSQL and migrations. For
the fail-closed Docker Compose production entrypoint, fixed Cloudflare Tunnel
mapping, upgrades, or data-retention instructions, see the
[deployment guide](docs/deployment.md). Tickety has one production target:
`https://tickety.nexora.com`.

> **Demo mode is on by default.** Public browsing does not require login. Sign in
> with the seeded administrator to configure the workspace and use protected AI,
> intelligence, integration, maintenance, ticket, and IAM features. Demo agents,
> supervisors, and the anonymous fallback remain blocked from those protected
> features.

**Default demo accounts** (also available for an explicit demo sign-in):
`alice@company.com` / `bob@company.com` / `carol@company.com` — password `tickety123`

Alice is the seeded demo administrator. Existing-user password changes are
disabled in demo mode; IAM administrators can still create users with an initial
password and manage profiles, roles, and account status. Automatic AI and
embedding workflows require `LOGIN_REQUIRED=true` in demo mode in addition to
their individual enable flags; explicitly requested admin operations remain
available without changing the public browsing mode.

## AI APIs

Tickety exposes exactly two AI entries. Microsoft Foundry is the default; a
single simplified Custom AI API is available for another OpenAI-compatible
endpoint. Named direct-provider and aggregator routes are not accepted.

| Entry | Model format | Required settings |
|---|---|---|
| **Microsoft Foundry** | `foundry/<deployment-name>` | `FOUNDRY_API_BASE` ending in `/openai/v1`; either `FOUNDRY_API_KEY` or `FOUNDRY_AUTH_METHOD=entra` |
| **Custom AI API** | `custom/<model-id>` | `CUSTOM_API_BASE` and `CUSTOM_API_KEY` |

Example Foundry configuration matching the current [OpenAI v1-compatible
Microsoft Foundry API](https://learn.microsoft.com/en-us/azure/foundry/openai/api-version-lifecycle):

```bash
FOUNDRY_API_BASE=https://<resource>.services.ai.azure.com/openai/v1
FOUNDRY_AUTH_METHOD=api_key
FOUNDRY_API_KEY=<foundry-key>
DEFAULT_MODEL=foundry/DeepSeek-V4-Flash
```

Set `FOUNDRY_AUTH_METHOD=entra` to use `DefaultAzureCredential` and automatic
token refresh instead of a key. The identity needs the applicable Foundry data
plane role. The Custom AI API intentionally has no provider-type, API-version,
temperature, or token-cap controls: endpoint, key, and model are the complete
configuration.

Both configured APIs are queried through `GET <base>/models` when the admin
catalog cache is stale (at most once every five minutes). The Settings page
also provides **Fetch Latest Models** for an immediate refresh.

### Ticket Intelligence Retrieval

Tickety can maintain a pgvector-backed retrieval index for tickets, public
ticket comments, and knowledge-base articles. This keeps LLM analysis cheap: SQL and
vector search narrow the database first, then the LLM only sees a short context
set.

Embeddings are opt-in to avoid surprise token spend:

```bash
TICKET_EMBEDDING_ENABLED=true
TICKET_EMBEDDING_MODEL=foundry/text-embedding-3-small
TICKET_EMBEDDING_DIMENSIONS=1536
TICKET_VECTOR_MIN_SCORE=0.25
```

After enabling embeddings, run `POST /ticket-intelligence/backfill` as an admin
to index existing records. Each call processes at most 500 records per source;
repeat it until `GET /ticket-intelligence/status` reports zero for
`legacy_ticket_documents`, `missing_ticket_documents`,
`missing_comment_documents`, and `missing_kb_documents`. New/updated tickets,
comments, synced tickets, and KB articles refresh or invalidate their documents
automatically. Private/internal comments are
excluded from external embeddings by default. Enabling
`TICKET_INDEX_PRIVATE_COMMENTS=true` is an explicit data-governance decision;
only published KB articles are indexed, and generated AI artifacts are never
treated as retrieval evidence. Embeddings share the same provider-wide
concurrency, request, token, and daily budgets as completions.

### AI reliability and cost controls

Every LLM task uses a strict output schema and a separate system policy that
treats ticket, KB, and retrieved text as untrusted evidence. Production fails
closed when a provider is missing, times out, or returns invalid output. Demo
mode can use local results only when `LLM_ALLOW_SYNTHETIC=true`; those artifacts
are persisted and displayed as synthetic. Generated escalation decisions
remain suggestions until a human applies the audited workflow action.
Automatic AI agents do not run in demo mode. In production they are opt-in;
set the specific `AUTO_*_ENABLED=true` controls only after authentication,
budgets, provider destinations, and egress policy are verified.
Anonymous self-service Portal tickets are never selected by the automatic AI
gap scanner. A scoped authenticated user must explicitly request analysis, or
an administrator/supervisor must explicitly queue it, before the worker may
send Portal content to an AI provider.

For an external integration, automatic AI remains an explicit, audited
binding-level opt-in. Once enabled, authoritative new/updated tickets are
queued immediately by sync/webhook ingestion, and the worker continuously
repairs missing enabled AI artifacts for external tickets active during the
previous seven days. The rolling repair is idempotent and bounded; it never
turns Portal tickets or a disabled/paused integration into implicit AI input.

Analysis is keyed by ticket input, model, and pipeline version. A durable claim
prevents API and worker processes from paying for the same analysis, unchanged
requests reuse the cached result, and bulk repair endpoints queue bounded worker
jobs instead of holding an HTTP request open. Operational limits include:

```bash
LLM_REQUEST_TIMEOUT_SECONDS=30
LLM_OVERALL_TIMEOUT_SECONDS=90
LLM_MAX_PROMPT_CHARS=32000
LLM_MAX_CONCURRENCY=4
LLM_DAILY_TOKEN_BUDGET=500000
LLM_PROVIDER_REQUESTS_PER_MINUTE=120
LLM_PROVIDER_TOKENS_PER_MINUTE=250000
AI_PIPELINE_TIMEOUT_SECONDS=900
AI_BACKGROUND_TICKETS_PER_SWEEP=5
AI_RISK_BACKFILL_PER_SWEEP=25
TICKET_EMBEDDING_MAX_COMMENTS_PER_REFRESH=50
AI_USER_REQUESTS_PER_MINUTE=10
AI_USER_REQUESTS_PER_DAY=200
ANALYTICS_USER_REQUESTS_PER_MINUTE=60
ANALYTICS_USER_REQUESTS_PER_DAY=5000
AI_INDEX_WRITES_PER_MINUTE=30
AI_INDEX_WRITES_PER_DAY=500
PORTAL_TICKETS_PER_MINUTE=5
PORTAL_TICKETS_PER_DAY=50
PORTAL_TICKETS_GLOBAL_PER_MINUTE=20
PORTAL_TICKETS_GLOBAL_PER_DAY=200
MAX_REQUEST_BODY_BYTES=1048576
AI_METRICS_RETENTION_DAYS=30
AI_ARTIFACT_RETENTION_DAYS=90
```

Provider concurrency uses expiring database-backed leases shared by API and
worker replicas; request and token ceilings are reserved before each retry.
The background worker admits at most `AI_BACKGROUND_TICKETS_PER_SWEEP` tickets
per scan (default 5, bounded to 1-25). Set the provider RPM/TPM values at or
below the actual Foundry deployment allocation; 429 retries honor both
`Retry-After` and Foundry's `retry-after-ms` response hint.
Legacy escalation-risk repair is separately capped by
`AI_RISK_BACKFILL_PER_SWEEP` (default 25, bounded to 1-100), records an explicit
completion marker, and never treats a legitimate zero score as missing.
Provider base URLs must use public HTTPS endpoints unless deployment-owned
private/insecure endpoint exceptions are deliberately enabled. Foundry URLs
must use a Microsoft Azure hostname and end in `/openai/v1`. In production,
both Foundry and custom hosts must be explicitly listed in
`LLM_ALLOWED_PROVIDER_HOSTS`. Prompt-free
latency, retry, token, failure, and synthetic-result counters are available to
admins and supervisors at `GET /admin/llm/metrics`.

Externally triggered AI, intelligence, provider settings, integrations, and AI
maintenance routes require a real authenticated session. In demo mode they are
limited to administrators; production retains its existing role permissions.
Demo fallback identities are never accepted on those routes. Provider-origin
changes also require the corresponding credential to be re-entered, preventing
an existing key from being silently forwarded to a new destination. External
webhooks are rejected unless `WEBHOOK_SECRET` is configured, the
`X-Freshservice-Webhook-Timestamp` is fresh, and the base64 HMAC-SHA256
signature matches `timestamp + "." + raw_body`. Signed deliveries are claimed
atomically so a captured request cannot be replayed.
OAuth callback state is likewise single-use, bounded, and charged to the
authenticated administrator's request budget before token exchange.

Production settings are deployment-owned by default. When
`TICKETY_ADMIN_SETTINGS_PORTAL_ENABLED=true`, an active authenticated `admin`
may save provider credentials, model routing, operational budgets, automation,
embedding, and Freshservice settings through the Settings page. Production
loads only overrides carrying an admin-approval marker, so stale demo rows do
not become active after a mode change. Secret values remain masked, destination
validation remains enforced, and workers refresh approved changes from the
database without requiring a worker-container restart.

Runtime mode, database and proxy URLs, private-network/provider allowlists,
CORS, cookie/login enforcement, Jira destinations, and SSO remain
deployment-managed trust boundaries. Change those values in the workload
environment through the ignored `.env` file, then use the audited
`./deploy.sh docker` release path.

## Production mode

For an isolated Freshservice proof of concept, see the [Freshservice trial POC guide](docs/freshservice-trial-poc.md). Trial bindings use a dedicated POC deployment and are never promoted into production.

Production Tickety is a one-way Freshservice sidecar. The provider adapter exposes only reads, the capability manifest permanently marks provider mutations unsupported, and the Freshworks package contains no write template. Manual ticket creation, ticket field updates, bulk lifecycle changes, deletion, and requester-portal submission are demo-only; make authoritative changes in Freshservice. AI summaries, retrieval indexes, recommendations, and other derived artifacts remain local to Tickety.

Freshservice synchronization is checkpointed and rate-aware. Every sweep reads
current-day and newly updated tickets first, commits each page before requesting
another, then admits a small ascending historical page and a small newest-first
conversation batch. List discovery excludes costly embedded resources, honors
the account-wide rate headers and `Retry-After`, and resumes every cursor after
a restart. The manual **Fetch tickets** action reprioritizes a recent window
without turning the HTTP request into an unbounded inventory import. Admins can
inspect all lanes at **Settings → Ticket sync status**.

Every fetched ticket's Freshservice status is reconciled into
`external_status`, `workflow_status`, and the displayed `status`. Resolved and
closed source states are displayed as `Closed`, with provider resolution
timestamps retained when available.

Identity is also one-way and non-federated: Tickety owns its own users, passwords, sessions, and roles. Freshservice agents and requesters are copied into a separate read-only external directory for ticket context only. Provider sync never creates or updates Tickety users, matches accounts by email/name, grants a Tickety role/session, assigns a local owner, or routes points to a local user.

Tickety ships in **demo mode** for evaluation with anonymous read access and an
explicitly authenticated administrator feature path. Production remains the
required mode for private deployments and deployment-managed security controls.
Set deployment environment/Secret values before starting production workloads:

`APP_MODE` is deployment-owned and cannot be changed through the settings API.
Production mode never creates the fixed demo accounts or sample data, even if
an old `SEED_DEMO_DATA` override exists. On the first production startup,
repository-seeded demo users are deactivated, their known passwords are erased,
their sessions are revoked, and queued/running demo-era AI work is quarantined
for review. Provision a separate real admin or SSO identity before switching
traffic.

1. Set `APP_MODE=production`, `LOGIN_REQUIRED=true`, secure cookie settings,
   and an exact `CORS_ALLOW_ORIGINS` value in the deployment Secret. Set
   `TICKETY_ADMIN_SETTINGS_PORTAL_ENABLED=true` only when authenticated admins
   should manage operational/provider settings from the portal.
2. Provision a non-demo administrator (or a reviewed SSO bootstrap path), then
   verify the documented demo credentials no longer work.
3. Optionally enable **SSO (OIDC)**. Microsoft Entra ID and Okta have guided
   presets; generic OpenID Connect providers remain supported. See the
   [SSO setup guide](docs/sso.md).

| Setting | What it does |
|---|---|
| Require Login | Controls whether users must sign in; configure it in the deployment environment/Secret. |
| Enable SSO | Enables OIDC-based Single Sign-On. It is deployment-managed in production. |
| Identity Provider | Selects the Entra ID, Okta, or generic OIDC preset; deployment-managed in production. |
| Tenant ID / Okta Domain | Generates provider discovery without requiring users to copy protocol URLs. |
| Client ID / Secret | Server-side OIDC credentials; the secret remains deployment-managed and is never returned to the browser. |
| Sign-in Redirect URI | Derived as `FRONTEND_URL + /api/auth/sso/callback` and must be registered exactly at the provider. |

### Background worker roles

Production API replicas do not run APScheduler. Scheduled external sync and AI
gap-filling jobs run in the dedicated `backend-worker` deployment, which has one
replica and uses a `Recreate` rollout so worker revisions never overlap. This
allows the `backend` API deployment to scale independently without duplicating
jobs.

The process role is controlled with `TICKETY_PROCESS_ROLE`:

| Value | Behaviour |
|---|---|
| `api` | Serve HTTP only; scheduled jobs are always disabled. |
| `worker` | Own scheduled jobs; use `python -m app.backend.worker`. |
| `all` | Combined API and scheduler process for local/demo use. |

When the variable is unset, production defaults to `api` and demo mode defaults
to `all`. `TICKETY_SCHEDULER_ENABLED=false` is an emergency kill switch for a
worker or combined process; setting it to true never grants scheduler ownership
to an `api` process. Sync intervals are bounded and controlled with
`SYNC_INTERVAL_SECONDS` and `AUTO_TRIAGE_INTERVAL_SECONDS`.
Seven-day automatic AI repair shares the same triage schedule and is capped by
`AI_BACKGROUND_TICKETS_PER_SWEEP`, so startup/backfill work drains gradually
through the same provider-wide Foundry budgets as realtime work.

## Modules

| Module | Key features |
|---|---|
| Incidents | Read-only Freshservice ticket projections with local AI triage, summaries, recommendations, and audit evidence; demo mode retains sample CRUD |
| Problems | Root cause tracking, link/unlink incidents, workaround/resolution documentation |
| Changes | CAB approvals (approve/reject), risk assessment (Low/Medium/High), rollback and test plans |
| Service Catalog | Requestable items with category grouping, approval routing, fulfilment tracking |
| Assets / CMDB | Hardware, software, licence, network inventory &mdash; ownership, warranty, location, cost tracking |
| Knowledge Base | Markdown articles, full-text search, category/tag filtering, helpful/not-helpful feedback, ticket linking |
| Portal | Public ticket submission and status tracking by email &mdash; no login required |
| Surveys / CSAT | Post-resolution survey templates, rating distribution, response rate analytics |
| Time Tracking | Per-ticket time entries, daily/total summaries, filter by ticket or agent |
| Reports | Volume trends (AreaChart), category/status breakdown (PieChart/BarChart), SLA compliance, resolution-time charts |
| AI Pipeline | Auto-triage (sentiment/category/priority/mood/complexity) &rarr; auto-summarisation &rarr; auto-routing &rarr; auto-resolution plans |
| Ticket Intelligence | Optional pgvector-backed retrieval over tickets, comments, and KB articles for low-token LLM database analysis |
| SLA | Per-priority clocks, breach detection, escalation risk scoring, compliance reports |
| Engagement | Impact points, tier promotions (T1&ndash;T8), momentum streaks, recognition badges, leaderboard |
| Auth / RBAC | Cookie-based sessions, admin / supervisor / agent roles, login page, SSO (OIDC) |
| Email | Private SendGrid delivery to Tickety/synced agents or synced Freshservice requesters, with server-resolved recipients and per-user limits |

## API

| Endpoint | Description |
|---|---|
| `GET /tickets` | List all tickets (filter by status, priority, assignee, category) |
| `POST /tickets` | Demo only: create a local sample ticket |
| `PATCH /tickets/:id` | Demo only: update a local sample ticket |
| `GET /tickets/:id/comments` | List comments (public and private) |
| `POST /tickets/:id/comments` | Add a Tickety-local annotation; never sent to Freshservice |
| `GET /tickets/:id/audit` | Audit log for a ticket |
| `POST /tickets/bulk` | Demo only: bulk-update local sample tickets |
| `GET /ticket-intelligence/search?q=...` | Retrieve the most relevant ticket/comment/KB snippets for a question |
| `POST /ticket-intelligence/analyze` | Ask an LLM a question using only retrieved ticket context |
| `POST /ticket-intelligence/backfill` | Admin: index existing tickets/comments/KB articles |
| `GET /problems` | List problems (filter by status) |
| `POST /problems` | Create problem record |
| `PATCH /problems/:id` | Update problem (status, root cause, resolution) |
| `POST /problems/:id/link/:ticket_id` | Link incident to problem |
| `GET /changes` | List change requests |
| `POST /changes` | Create change request |
| `PATCH /changes/:id` | Update change (status, risk, schedule) |
| `POST /changes/:id/approvals` | Add CAB approval |
| `PATCH /changes/:id/approvals/:aid` | Approve or reject change |
| `GET /assets` | List assets (filter by type, status, search) |
| `POST /assets` | Create asset record |
| `GET /kb` | Search knowledge base articles |
| `POST /kb` | Create article |
| `GET /services` | List service catalog items |
| `GET /service-requests` | List service requests |
| `POST /surveys/send` | Send CSAT survey for a resolved ticket |
| `GET /surveys/stats` | Survey response statistics |
| `POST /time-entries` | Log time on a ticket |
| `GET /reports/summary` | KPI dashboard data |
| `GET /reports/volume` | 30-day ticket volume |
| `GET /intelligence/alerts` | Escalation-prone tickets, SLA at-risk/breached |
| `GET /intelligence/systemic` | Systemic issue clusters |
| `GET /leaderboard` | Agent leaderboard (points, tier, rank) |
| `GET /admin/sync/status` | Admin: recent, historical, conversation, and Freshservice rate-budget checkpoints |
| `POST /admin/sync/trigger` | Admin: run one bounded provider sync sweep |
| `POST /auth/login` | Session login (cookie) |
| `POST /auth/logout` | Clear session |
| `GET /auth/sso/config` | Check if SSO is enabled |
| `GET /auth/sso/login` | Initiate OIDC login flow |
| `GET /auth/sso/callback` | OIDC provider callback |
| `GET /admin/settings` | List configuration keys |
| `PUT /admin/settings` | Update configuration |
| `GET /email/status` | Check whether SendGrid delivery is configured (no secret material) |
| `GET /email/recipients` | Search the authorized agent or requester recipient directory |
| `POST /email/send` | Send separate private SendGrid deliveries to server-resolved recipients |

## Settings

| Section | What you configure |
|---|---|
| LLM | Microsoft Foundry or Custom AI API, default model, endpoint credentials, automatic model fetching |
| Freshservice sidecar | Read-only Freshservice credentials, conservative per-sweep limits, API budget reserve, and ticket sync status |
| SLA targets | Resolution-time targets per priority (P1/P2/P3 hours) |
| Agents | Create and manage accounts, assign admin/supervisor/agent roles |
| Categories | Ticket classification categories with colour coding |
| Statuses | Custom ticket lifecycle statuses (open/terminal flags, sort order) |
| Priorities | Custom priority levels with per-priority SLA hours and sort weights |
| Organisation | Workspace name, logo URL, primary colour |
| SendGrid email | Masked API key, verified sender, reply-to address, and per-user delivery limits |
| AI Automation | Toggle: auto-triage, auto-summarisation, auto-routing, auto-resolution, systemic detection |
| Security & Auth | Require Login (production mode), SSO/OIDC (Microsoft Entra ID, Okta, generic) |
| Notifications | Enable/disable alert events (new ticket, SLA breach, escalation, assignment, comment) per channel (in-app/email/webhook) |
| Maintenance | Repair AI data gaps, retroactively triage untriaged tickets |

## Structure

```
app/
├── backend/
│   ├── main.py              FastAPI app + all endpoints
│   ├── database.py          SQLAlchemy models (20 tables)
│   ├── schema.py            Pydantic request/response models
│   ├── settings.py          DB-backed env override persistence
│   ├── sync_worker.py       Role-gated background scheduler lifecycle
│   ├── worker.py            Dedicated production scheduler entrypoint
│   ├── brain.py             LLM-powered ticket processor
│   ├── intelligence.py      AI agents (escalation, SLA, systemic, trends, routing)
│   ├── llm_manager.py       LiteLLM router + live model fetching
│   ├── prompts.py           Gamification rules and thresholds
│   ├── seed.py              Demo data (users, tickets, KB, config)
│   └── integrations/
│       ├── base.py           Abstract ITSM adapter interface
│       ├── freshservice.py   Read-only Freshservice adapter (REST + OAuth)
│       ├── jira.py           Legacy read-only Jira import adapter
│       ├── registry.py       Adapter factory
│       └── sync.py           Ticket sync and external user directory refresh
└── frontend-next/
    ├── app/
    │   ├── page.tsx           Dashboard
    │   ├── tickets/           List view + detail page
    │   ├── agents/            Agent CRUD + role management
    │   ├── services/          Service catalog
    │   ├── problems/          Problem management
    │   ├── changes/           Change management
    │   ├── assets/            Asset / CMDB
    │   ├── knowledge/         Knowledge base
    │   ├── surveys/           CSAT surveys
    │   ├── time/              Time tracking
    │   ├── portal/            Self-service portal
    │   ├── reports/           Reports & analytics
    │   ├── leaderboard/       Agent leaderboard
    │   ├── intelligence/      AI intelligence dashboard
    │   ├── settings/          System configuration
    │   ├── login/             Authentication
    │   └── profile/           User profile
    ├── components/
    │   ├── layout/            Sidebar, shell, footer, logo, and error boundaries
    │   ├── dashboard/         KPI cards
    │   ├── ticket/            AI stream, ticket list, modals
    │   └── ui/                Shared UI (searchable select)
    └── lib/                   API client, types, utilities, WebSocket, stores
deploy/local-tunnel/           Fixed production TLS proxy configuration
scripts/                       Compose production validation and verification
```

Production schema changes use forward-only Alembic migrations. See
[Database migrations](docs/database-migrations.md) for deployment, backup, and
recovery expectations.

## License

MIT
