<div align="center">
  <img src="https://img.shields.io/badge/python-3.11-blue" alt="Python 3.11">
  <img src="https://img.shields.io/badge/next.js-14.2-black" alt="Next.js 14">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT">
</div>

---

Tickety — ITSM platform with built-in AI. Runs standalone or connects to an external provider.

## Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.11 · FastAPI · SQLAlchemy · APScheduler |
| Frontend | Next.js 14 · Tailwind CSS · TanStack Query · Recharts |
| AI | LiteLLM (DeepSeek · OpenAI · OpenRouter · Azure) |
| Database | PostgreSQL |
| Infra | Docker · Kubernetes · OrbStack |

## Quick start

```bash
cp .env.example .env   # set DEEPSEEK_API_KEY and DATABASE_URL
docker compose up -d    # or ./deploy.sh for K8s
open http://localhost:3000
```

Demo accounts: `alice@company.com` / `bob@company.com` / `carol@company.com` — password `tickety123`

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
| SLA | Per-priority clocks, breach detection, escalation risk scoring, compliance reports |
| Engagement | Impact points, tier promotions (T1&ndash;T8), momentum streaks, recognition badges, leaderboard |
| Auth / RBAC | Cookie-based sessions, admin / supervisor / agent roles, login page |

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
| `GET /admin/settings` | List configuration keys |
| `PUT /admin/settings` | Update configuration |

## Settings

| Section | What you configure |
|---|---|
| LLM | Provider (DeepSeek/OpenAI/OpenRouter/Azure), default model, API keys, live model catalogue fetching |
| Ticketing mode | Standalone (built-in) or external ITSM provider |
| SLA targets | Resolution-time targets per priority (P1/P2/P3 hours) |
| Agents | Create and manage accounts, assign admin/supervisor/agent roles |
| Categories | Ticket classification categories with colour coding |
| Statuses | Custom ticket lifecycle statuses (open/terminal flags, sort order) |
| Priorities | Custom priority levels with per-priority SLA hours and sort weights |
| Organisation | Workspace name, logo URL, primary colour |
| AI Automation | Toggle: auto-triage, auto-summarisation, auto-routing, auto-resolution, systemic detection |
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
│   ├── sync_worker.py       Background scheduler
│   ├── brain.py             LLM-powered ticket processor
│   ├── intelligence.py      AI agents (escalation, SLA, systemic, trends, routing)
│   ├── llm_manager.py       LiteLLM router + live model fetching
│   ├── prompts.py           Gamification rules and thresholds
│   ├── seed.py              Demo data (users, tickets, KB, config)
│   └── integrations/
│       ├── base.py           Abstract ITSM adapter interface
│       ├── freshservice.py   External provider adapter (REST + OAuth)
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
k8s/                           Namespace, secrets, backend, frontend, postgres manifests
```

## License

MIT
