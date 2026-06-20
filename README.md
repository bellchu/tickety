<div align="center">
  <img src="https://img.shields.io/badge/python-3.11-blue" alt="Python 3.11">
  <img src="https://img.shields.io/badge/next.js-14.2-black" alt="Next.js 14">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT">
</div>

---

Tickety — ITSM platform with built-in AI. Runs standalone or connects to an external provider.

## Stack

Python 3.11 + FastAPI + SQLAlchemy · Next.js 14 + Tailwind · PostgreSQL · LiteLLM · Docker + K8s

## Quick start

```bash
cp .env.example .env   # set DEEPSEEK_API_KEY and DATABASE_URL
docker compose up -d    # or ./deploy.sh for K8s
open http://localhost:3000
```

Demo accounts: `alice@company.com` / `bob@company.com` / `carol@company.com` — password `tickety123`

## Modules

| Module | |
|---|---|
| **Incidents** | Ticket CRUD, comments, audit log, bulk ops, custom statuses |
| **Problems** | Root cause tracking, incident linking |
| **Changes** | CAB approvals, risk assessment, rollback plans |
| **Service Catalog** | Requestable items, approval routing |
| **Assets / CMDB** | Hardware, software, licence inventory |
| **Knowledge Base** | Articles, search, ticket linking |
| **Portal** | Public ticket submission &amp; tracking |
| **Surveys / CSAT** | Post-resolution rating &amp; feedback |
| **Time Tracking** | Per-ticket time entries |
| **Reports** | Volume, SLA, resolution-time charts |
| **AI Pipeline** | Auto-triage, summarisation, routing, resolution |
| **SLA** | Per-priority clocks, breach alerts |
| **Engagement** | Points, tiers, momentum, leaderboard |
| **Auth / RBAC** | Sessions, admin/supervisor/agent roles |

## Settings

LLM provider/model · Ticketing mode (standalone/external) · SLA targets · Agents · Custom statuses/priorities · AI toggles · Notifications

## Structure

```
app/
├── backend/
│   ├── main.py              FastAPI app
│   ├── database.py          SQLAlchemy models
│   ├── intelligence.py      AI agents (risk, SLA, systemic, trends)
│   ├── llm_manager.py       LiteLLM router
│   └── integrations/        External provider adapters
└── frontend-next/
    ├── app/                 Next.js pages
    ├── components/          React components
    └── lib/                 API client, types, utils
k8s/                         Kubernetes manifests
deploy.sh                    Build + deploy
```

## License

MIT
