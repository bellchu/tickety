# Kubernetes configuration

The manifests in this directory expect a `tickety-secrets` Secret in the
`tickety` namespace. Secret values are intentionally not stored in this
repository and must be supplied by the deployment environment or a secret
manager before applying the workloads.

For a local cluster, create the namespace and secret without writing the
values to disk:

```sh
kubectl apply -f k8s/namespace.yaml
kubectl -n tickety create secret generic tickety-secrets \
  --from-literal=APP_MODE=production \
  --from-literal=SEED_DEMO_DATA=false \
  --from-literal=LOGIN_REQUIRED=true \
  --from-literal=POSTGRES_PASSWORD='<generate-a-strong-password>' \
  --from-literal=DATABASE_URL='postgresql+psycopg2://tickety:<url-encoded-password>@postgres:5432/tickety' \
  --from-literal=FRONTEND_URL='https://support.example.com' \
  --from-literal=CORS_ALLOW_ORIGINS='https://support.example.com' \
  --from-literal=LLM_ALLOWED_PROVIDER_HOSTS='your-reviewed-provider.example.com' \
  --from-literal=WEBHOOK_SECRET='<generate-a-random-secret>' \
  --from-literal=WEBHOOK_MAX_AGE_SECONDS=300 \
  --from-literal=ITSM_PROVIDER='jira' \
  --from-literal=SYNC_INTERVAL_SECONDS=60
```

Add only the provider and AI credentials required by the deployment. Prefer
an external secret controller in shared or production clusters. Never commit
rendered Secret manifests or plaintext credentials.

The database password in `DATABASE_URL` must be URL-encoded and must match
`POSTGRES_PASSWORD`. Apply the remaining manifests only after the Secret
exists.

Apply `network-policy.yaml` with the workloads (for example,
`kubectl apply -n tickety-standalone -f k8s/network-policy.yaml` for a public
standalone namespace). It restricts backend and worker
egress to cluster DNS, the Tickety Postgres pod, and public IPv4 destinations.
Public provider egress is limited to TCP 443.
This is the connection-time SSRF/DNS-rebinding boundary for configurable AI
and ITSM endpoints; clusters must use a CNI that enforces Kubernetes
NetworkPolicy. The canonical local deployment runs
`verify-network-policy.sh` and aborts unless a reachable private canary is
blocked while public HTTPS remains available. Target-specific deployment
workflows must run the same check with their namespace. Private AI endpoints require a deliberately reviewed policy
change rather than only an application setting.

Before exposing a database that has ever run in demo mode, provision a real
administrator or reviewed SSO bootstrap path. Production startup disables the
fixed `u-alice`, `u-bob`, and `u-carol` demo identities, erases their known
passwords, and revokes their sessions. Rotate every configured AI-provider
credential when upgrading an installation that was previously reachable in
demo mode, and audit the stored provider origins before enabling AI traffic.

After an upgrade that changes retrieval evidence, call the protected
`POST /ticket-intelligence/backfill` endpoint in batches and require
`GET /ticket-intelligence/status` to report zero legacy and missing ticket,
comment, and published-KB documents before enabling retrieval-backed AI. Each
call is bounded to 500 records per source; repeat it until the status converges.
If embeddings are enabled, confirm provider budget before a forced backfill.

OrbStack's built-in local Kubernetes networking currently accepts but does not
enforce NetworkPolicy. The local `deploy.sh` therefore reports that limitation
and continues; remote and public-cluster deployment paths retain the mandatory
enforcement check.
