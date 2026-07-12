<div align="center">
  <img src="https://img.shields.io/badge/python-3.11-blue" alt="Python 3.11">
  <img src="https://img.shields.io/badge/next.js-14.2-black" alt="Next.js 14">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT">
</div>

---

Tickety — ITSM platform with built-in AI. Runs standalone or connects to an external provider.

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
| Frontend | Next.js 14 · Tailwind CSS · TanStack Query · Recharts |
| AI | LiteLLM (DeepSeek · OpenAI · OpenRouter · Azure · Custom) |
| Database | PostgreSQL |
| Infra | Docker · Kubernetes · OrbStack |

## Quick start

Python dependencies are declared in `requirements.txt` and reproducibly pinned
in `requirements.lock`. CI and production images install the lock. After an
intentional dependency change, regenerate it with:

```bash
uv pip compile requirements.txt --universal --python-version 3.11 --output-file requirements.lock
```

```bash
cp .env.example .env   # configure DATABASE_URL (and your preferred LLM keys)
docker compose up -d    # or ./deploy.sh for K8s
open http://localhost:3000
```

> **Demo mode is on by default.** No login required — the app auto-signs you in as the first active user (Alice Chen, admin). To require authentication, go to **Settings → Security & Auth** and enable **"Require Login"**. See [Production mode](#production-mode) below.

**Default demo accounts** (when login is required):
`alice@company.com` / `bob@company.com` / `carol@company.com` — password `tickety123`

## LLM Providers

Tickety supports **5 built-in providers** plus a **custom provider** for any OpenAI-compatible endpoint.

> **Recommended:** [DeepSeek](https://deepseek.com) offers the best price/performance ratio among all major providers — excellent triage and summarization quality at a fraction of the cost.

| Provider | Model format | Notes |
|---|---|---|
| **DeepSeek** | `deepseek-v4-flash`, `deepseek-v4-pro` | Best value — needs `DEEPSEEK_API_KEY` |
| **OpenAI** | `openai/gpt-4o`, `openai/gpt-4o-mini` | Needs `OPENAI_API_KEY`, optional `OPENAI_API_BASE` for proxies |
| **OpenRouter** | `openrouter/<model-id>` | Aggregates 200+ models — `OPENROUTER_API_KEY` |
| **Azure** | `azure/<deployment-name>` | Azure OpenAI — `AZURE_API_KEY` + `AZURE_API_BASE` + `AZURE_API_VERSION` |
| **Azure AI** | `azure_ai/<model-id>` | Models as a Service — `AZURE_AI_API_KEY` + `AZURE_AI_API_BASE` |
| **Custom** | `custom/<any-model>` | Any OpenAI-compatible API (vLLM, Ollama, Groq, Together AI, etc.) |

### Custom Provider

Configure any OpenAI-compatible endpoint via **Settings → LLM Configuration → Custom (OpenAI-compatible)**:

| Setting | Description |
|---|---|
| Custom API Key | Your provider's API key |
| Custom API Base URL | Endpoint URL (e.g. `https://api.groq.com/openai/v1`) |
| LiteLLM Provider Type | Default `openai` — also supports `anthropic`, `gemini`, `groq`, `together_ai` etc. |
| API Version | Optional (e.g. `2024-10-21`) |
| Temperature | Optional 0–2 (e.g. `0.7`) |
| Max Tokens | Optional (e.g. `4096`) |
| Default Model | Free-text — type any model name your provider supports |
| **Fetch Latest Models** | Auto-discovers available models from your custom endpoint |

### Ticket Intelligence Retrieval

Tickety can maintain a pgvector-backed retrieval index for tickets, ticket
comments, and knowledge-base articles. This keeps LLM analysis cheap: SQL and
vector search narrow the database first, then the LLM only sees a short context
set.

Embeddings are opt-in to avoid surprise token spend:

```bash
TICKET_EMBEDDING_ENABLED=true
TICKET_EMBEDDING_MODEL=openai/text-embedding-3-small
TICKET_EMBEDDING_DIMENSIONS=1536
```

After enabling embeddings, run `POST /ticket-intelligence/backfill` as an admin
to index existing records. New/updated tickets, comments, synced tickets, and KB
articles refresh their documents automatically.

## Production mode

Tickety ships in **demo mode** — no authentication needed. For production:

`APP_MODE` is deployment-owned and cannot be changed through the settings API.
Production mode never creates the fixed demo accounts or sample data, even if
an old `SEED_DEMO_DATA` override exists.

1. Go to **Settings → Security & Auth**
2. Enable **"Require Login"** — all API endpoints will require a valid session
3. Optionally enable **SSO (OIDC)** — supports Google, Azure AD, Okta, and any OpenID Connect provider

| Setting | What it does |
|---|---|
| Require Login | Toggle on/off. When off (default), any visitor is auto-signed in as the first active user. When on, users must sign in via email/password or SSO. |
| Enable SSO | Enable OIDC-based Single Sign-On. Users see a "Sign in with SSO" button on the login page. |
| SSO Provider Name | Display name shown on the SSO login button (e.g. "Google", "Okta"). |
| Client ID / Secret | OIDC credentials from your identity provider. |
| Discovery URL | Provider's `.well-known/openid-configuration` endpoint. |
| Redirect URI | Must match the callback URL registered with your provider (e.g. `https://yourdomain.com/api/auth/sso/callback`). |

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

## Modules

| Module | Key features |
|---|---|
| Incidents | CRUD, comments (public/private), audit log, bulk ops, tags, custom statuses &mdash; fully triaged by AI pipeline |
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

## API

| Endpoint | Description |
|---|---|
| `GET /tickets` | List all tickets (filter by status, priority, assignee, category) |
| `POST /tickets` | Create ticket (auto-triaged by AI) |
| `PATCH /tickets/:id` | Update ticket status, assignee, priority etc. |
| `GET /tickets/:id/comments` | List comments (public and private) |
| `POST /tickets/:id/comments` | Add comment |
| `GET /tickets/:id/audit` | Audit log for a ticket |
| `POST /tickets/bulk` | Bulk assign/close/set priority/ set category |
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
| `POST /auth/login` | Session login (cookie) |
| `POST /auth/logout` | Clear session |
| `GET /auth/sso/config` | Check if SSO is enabled |
| `GET /auth/sso/login` | Initiate OIDC login flow |
| `GET /auth/sso/callback` | OIDC provider callback |
| `GET /admin/settings` | List configuration keys |
| `PUT /admin/settings` | Update configuration |

## Settings

| Section | What you configure |
|---|---|
| LLM | Provider (DeepSeek/OpenAI/OpenRouter/Azure/Custom), default model, API keys, live model fetching |
| Ticketing mode | Standalone (built-in) or external ITSM provider |
| SLA targets | Resolution-time targets per priority (P1/P2/P3 hours) |
| Agents | Create and manage accounts, assign admin/supervisor/agent roles |
| Categories | Ticket classification categories with colour coding |
| Statuses | Custom ticket lifecycle statuses (open/terminal flags, sort order) |
| Priorities | Custom priority levels with per-priority SLA hours and sort weights |
| Organisation | Workspace name, logo URL, primary colour |
| AI Automation | Toggle: auto-triage, auto-summarisation, auto-routing, auto-resolution, systemic detection |
| Security & Auth | Require Login (production mode), SSO/OIDC (Google, Azure AD, Okta, generic) |
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
│       ├── freshservice.py   External provider adapter (REST + OAuth)
│       ├── jira.py           Jira Cloud adapter (REST + API token)
│       ├── registry.py       Adapter factory
│       └── sync.py           Ticket & agent sync logic
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
    │   ├── layout/            Sidebar, footer, logo, sync indicator
    │   ├── dashboard/         KPI cards
    │   ├── engagement/        Sentiment, momentum, recognitions, tiers
    │   ├── ticket/            AI stream, ticket list, modals
    │   └── ui/                Shared UI (searchable select)
    └── lib/                   API client, types, utilities, WebSocket, stores
k8s/                           Namespace, workloads, database, and secret setup guidance
```

Production schema changes use forward-only Alembic migrations. See
[Database migrations](docs/database-migrations.md) for deployment, backup, and
recovery expectations.

## License

MIT
