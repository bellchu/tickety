<p align="center">
  <img src="app/frontend-next/public/brand/tickety-mark.svg" alt="Tickety OPS Tower mark" width="88">
</p>

<h1 align="center">Tickety OPS Tower</h1>

<p align="center">Self-hosted intelligence for IT service operations.</p>

Tickety brings ticket queues, SLA monitoring, reports, knowledge, business
requirements, and optional AI analysis into one workspace. In production, it reads Freshservice records
into a local store without writing ticket changes back to Freshservice.

Built with FastAPI, Next.js, and PostgreSQL. Runs with Docker Compose or
Kubernetes/Helm.

## Requirements workspace

Open **Work → Requirements** (`/requirements`) to capture an approved project,
request, or enhancement around a business objective. Evidence, questions,
requirements, and user stories stay connected in one workspace. **Worth your
attention** suggests the next useful action from current blockers and business
priorities; users can revisit any part of the work without following a fixed wizard.

- **Bring business context:** paste material or preview TXT, Markdown, EML, DOCX,
  selectable-text PDF, VTT, and SRT files. Classify sources as documents, emails,
  SOPs, or meeting transcripts. Saved evidence is immutable and traceable.
- **Clarify scope:** capture exact evidence excerpts, outcomes, priorities, and
  observable acceptance criteria. Assign business questions to an answer-owner
  role and distinguish blocking decisions from exploratory questions. Keep
  background material and deferred needs without treating them as current delivery.
- **Review with accountability:** compare selected requirements for possible
  conflicts using optional AI assistance. Humans record decisions and sign off
  a specific revision with their review capacity and rationale. Changes to agreed
  scope withdraw its sign-off and story until reviewed again.
- **Prepare the handoff:** create user stories from signed-off requirements,
  copy their acceptance criteria and provenance, or export a Markdown BRD with
  priorities, evidence, decisions, and outstanding exploration. These actions do
  not create external development tickets or constitute deployment approval.

An active session is required, including in demo mode. Initiatives are accessible
to their creator and active administrators. AI requires a configured, available
provider; manual work remains available without it. Suggestions never sign off
requirements or automatically record business decisions.

Uploads are limited to 400 KB and confirmed source text to 100,000 characters.
Scanned PDFs require OCR or transcription beforehand. Unsaved drafts stay only in
the current tab's memory while navigating: save before refreshing or signing out.
See the [business guide](docs/requirements-gathering.md) and
[runtime boundaries](docs/requirements-runtime.md) for details.

## Quick start

For the maintained `dev` branch on MicroK8s, use the
[Dev deployment guide](docs/dev-deployment.md). The isolated Compose evaluation
path below is a separate deployment option.

Requires Docker and Docker Compose 2.24 or later. Run these commands from the
repository root.

1. Copy the environment template:

   ```bash
   cp .env.example .env
   ```

2. Edit `.env` for isolated local evaluation:

   ```dotenv
   APP_MODE=demo
   LOGIN_REQUIRED=true
   ITSM_PROVIDER=standalone
   FRONTEND_URL=http://localhost:3000
   CORS_ALLOW_ORIGINS=http://localhost:3000
   POSTGRES_PASSWORD=replace-with-a-long-random-password
   DATABASE_URL=postgresql+psycopg2://tickety:replace-with-a-long-random-password@postgres:5432/tickety
   ```

   Use the same password in both database settings. URL-encode reserved
   characters in `DATABASE_URL`. Keep `.env` and credentials out of Git.

3. Start the stack:

   ```bash
   ./deploy.sh docker
   ```

4. Create the first administrator:

   ```bash
   docker compose run --rm backend \
     python -m app.backend.bootstrap_admin \
     --name "Project Owner" \
     --email owner@example.com
   ```

   Enter a password of at least 12 characters at the hidden prompt. This command
   works only while the users table is empty; no accounts or sample data are
   created automatically.

Open [localhost:3000](http://localhost:3000) and sign in. Stop the stack with
`docker compose down`; the database is retained.

## Configuration

See [.env.example](.env.example) for all settings.

- **Production:** The template defaults to `APP_MODE=production`, which requires
  an authenticated session and uses the read-only Freshservice sidecar. Follow
  the [deployment guide](docs/deployment.md) for HTTPS, origins, secrets, and
  infrastructure setup. Keep demo mode local.
- **AI:** Configure Microsoft Foundry (`FOUNDRY_*`) or an OpenAI-compatible
  endpoint (`CUSTOM_*`), select `DEFAULT_MODEL`, and set
  `LLM_ALLOWED_PROVIDER_HOSTS` for production. Automatic AI workflows and
  embeddings are off by default.
- **SSO:** Use the [SSO guide](docs/sso.md) to configure Entra ID, Okta, or
  another OIDC provider.

## Development

Backend checks require Python 3.11 and dependencies from `requirements.lock`.
Run in an activated virtual environment:

```bash
python -m pip install -r requirements.lock
APP_MODE=demo DATABASE_URL=sqlite:// PYTHONPATH=. \
  python -m unittest discover -s tests -p 'test_*.py' -v
```

Frontend checks require Node.js 24 or later and npm 12.0.2:

```bash
cd app/frontend-next
npm ci
npm test
npm run lint
npm run typecheck
npm run build
npm run verify:production-routes
```

The production-route check runs against the completed build. Test and browser
verification history for the requirements workspace is recorded
[separately](docs/requirements-verification.md); local checks do not establish that
a commit has been deployed to Dev or production.

## Documentation

- [Deployment](docs/deployment.md) — Docker Compose and production Kubernetes
- [Development deployment](docs/dev-deployment.md) — MicroK8s
- [Database migrations](docs/database-migrations.md)
- [Requirements gathering](docs/requirements-gathering.md) — business workflow and user guide
- [Requirements runtime](docs/requirements-runtime.md) — access, capacity, extraction, AI, and audit boundaries
- [Requirements verification](docs/requirements-verification.md) — regression scenarios and recorded validation limits
- [Freshworks app](freshworks-app/README.md)
- [RAG operations](docs/rag-v2.md) — indexing, rollout, and rollback

## License

[MIT](LICENSE)
