<p align="center">
  <img src="app/frontend-next/public/brand/tickety-mark.svg" alt="Tickety OPS Tower mark" width="88">
</p>

<h1 align="center">Tickety OPS Tower</h1>

<p align="center">Self-hosted intelligence for IT service operations.</p>

Tickety brings ticket queues, SLA monitoring, reports, knowledge, and optional
AI analysis into one workspace. In production, it reads Freshservice records
into a local store without writing ticket changes back to Freshservice.

Built with FastAPI, Next.js, and PostgreSQL. Runs with Docker Compose or
Kubernetes/Helm.

## Quick start

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
```

## Documentation

- [Deployment](docs/deployment.md) — Docker Compose and production Kubernetes
- [Development deployment](docs/dev-deployment.md) — MicroK8s
- [Database migrations](docs/database-migrations.md)
- [Requirements gathering](docs/requirements-gathering.md) — source evidence, sign-off, BRD and user stories
- [Freshworks app](freshworks-app/README.md)
- [RAG operations](docs/rag-v2.md) — indexing, rollout, and rollback

## License

[MIT](LICENSE)
