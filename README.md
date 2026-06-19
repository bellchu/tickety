<div align="center">
  <img src="https://img.shields.io/badge/python-3.11-blue" alt="Python 3.11">
  <img src="https://img.shields.io/badge/next.js-14.2-black" alt="Next.js 14">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT">
</div>

---

**Tickety** is an intelligent IT support operations platform that connects to Freshservice, ingests tickets, and runs an ambient AI workforce over them — fully automatic, zero‑click. Every ticket gets triaged, summarised, routed to the best engineer, and given a step‑by‑step resolution plan without any human interaction.

## What it does

| Feature | Detail |
|---|---|
| **Auto‑triage** | Sentiment, category, priority, mood, complexity — scored on every incoming ticket |
| **Auto‑summarisation** | 2–3 sentence case summary for support managers |
| **Auto‑routing** | Recommends the best engineer based on skills, tier, and workload |
| **Auto‑resolution** | Step‑by‑step resolution plan with root‑cause hypothesis and escalation advice |
| **Systemic issue detection** | Clusters similar tickets to surface broad business‑impact patterns |
| **SLA enforcement** | Per‑priority SLA clocks with pre‑breach alerts and breach tracking |
| **Agent workload** | Per‑agent open ticket counts, resolution volumes, and average resolution time |
| **Leaderboard** | Impact‑point leaderboard with tier promotions and recognition badges |
| **Live model fetching** | Pulls the latest available models from DeepSeek, OpenAI, and OpenRouter |
| **OAuth 2.0** | Freshworks App SDK‑compatible authentication + API key fallback |

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌───────────┐
│  Freshservice │────▶│  Tickety     │────▶│  LLM      │
│  (webhook +  │     │  Backend     │     │  (DeepSeek,│
│   REST API)  │     │  (FastAPI)   │     │   OpenAI,  │
└─────────────┘     └──────┬───────┘     │   OpenRtr) │
                           │             └───────────┘
                    ┌──────▼───────┐
                    │  PostgreSQL  │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │  Frontend    │
                    │  (Next.js)   │
                    └──────────────┘
```

- **Backend**: Python 3.11 + FastAPI + SQLAlchemy + APScheduler
- **Frontend**: Next.js 14 (App Router) + Tailwind CSS + TanStack Query
- **LLM**: LiteLLM router — one model string, any provider (DeepSeek, OpenAI, OpenRouter, Azure)
- **Database**: PostgreSQL
- **Orchestration**: Kubernetes (OrbStack) with Docker images

## Quick start

### 1. Clone & configure

```bash
git clone https://github.com/your-org/tickety.git
cd tickety
cp .env.example .env
# Edit .env — set at minimum:
#   FRESHSERVICE_DOMAIN, FRESHSERVICE_API_KEY
#   DEEPSEEK_API_KEY (or OPENAI_API_KEY / OPENROUTER_API_KEY)
#   DATABASE_URL
```

### 2. Run with Docker Compose

```bash
docker compose up -d
```

### 3. Run on Kubernetes

```bash
# Set your secrets in k8s/secrets.yaml first
./deploy.sh
```

### 4. Open the UI

```
http://localhost:3000
```

## Settings walkthrough

1. **LLM Model** — pick your provider (DeepSeek, OpenAI, OpenRouter) and model. Click **"Fetch Latest Models"** to pull the live model catalogue.
2. **ITSM Integration** — configure your Freshservice domain, API key, webhook secret, and SLA targets (P1/P2/P3 hours).
3. **Agent Accounts** — click **"Fetch Agents"** to pull agents from Freshservice and auto‑create Tickety accounts.
4. **OAuth 2.0** — set up Freshworks OAuth if you prefer token‑based auth over API keys.

## API

| Endpoint | Description |
|---|---|
| `GET /tickets` | List all tickets |
| `POST /tickets` | Create a ticket (auto‑triaged) |
| `POST /admin/sync/fetch` | Import tickets from Freshservice |
| `POST /admin/sync/agents` | Import agents from Freshservice |
| `POST /admin/sync/repair` | Fill missing AI data gaps |
| `POST /admin/llm/refresh-models` | Fetch latest LLM models |
| `GET /intelligence/systemic` | Systemic issue clusters |
| `GET /intelligence/workload` | Agent workload dashboard |
| `GET /intelligence/sla` | SLA clock status |
| `POST /oauth/authorize` | OAuth 2.0 flow start |
| `POST /oauth/callback` | OAuth 2.0 token exchange |

## Project structure

```
app/
├── backend/
│   ├── main.py              FastAPI app + all endpoints
│   ├── intelligence.py      Ambient AI agents (risk, SLA, systemic, trends)
│   ├── brain.py             LLM-powered ticket processor
│   ├── llm_manager.py       LiteLLM router + live model fetching
│   ├── database.py          SQLAlchemy models + migrations
│   ├── schema.py            Pydantic request/response models
│   ├── settings.py          Settings persistence (DB-backed env overrides)
│   ├── sync_worker.py       Background scheduler (ticket sync + AI scanner)
│   └── integrations/
│       ├── freshservice.py  Freshservice API adapter (REST + OAuth)
│       └── sync.py          Ticket & agent sync logic
└── frontend-next/
    ├── app/                 Next.js App Router pages
    ├── components/          React components (dashboard, tickets, engagement, UI)
    ├── lib/                 API client, types, utilities, engagement store
    └── public/              Static assets + Freshworks manifest.json
k8s/                         Kubernetes manifests
Dockerfile                   Multi-stage build (backend + frontend)
deploy.sh                    One-shot build + deploy to K8s
```

## License

MIT
