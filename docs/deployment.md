# Deploying Tickety

Tickety runs PostgreSQL, a migration job, the FastAPI backend, the Next.js
frontend, and one worker for scheduled ITSM synchronization and opt-in AI
jobs. The Docker Compose and Helm paths run migrations before starting the
backend and worker.

## Docker Compose

Docker Compose is the quickest way to evaluate Tickety. It uses a private
PostgreSQL service, a persistent named volume, and exposes only the frontend.
Install Docker Engine or Docker Desktop with Docker Compose 2.24 or later.

```sh
./deploy.sh docker
```

Then open `http://localhost:3000`. The command builds the images, waits for the
database and migration service, and waits for the frontend health check. Use
`TICKETY_PORT` in `.env` to publish a different host port.

The default mode is a demo. It has seeded sample data and the demo accounts
documented in the project README. Do not expose this mode to untrusted users.
To stop it while retaining database data:

```sh
docker compose down
```

`docker compose down --volumes` also removes the `pgdata` database volume.

### Docker production configuration

Copy `.env.example` to `.env`, set the following values, and then run
`./deploy.sh docker`:

```dotenv
APP_MODE=production
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
`POSTGRES_*` values; URL-encode credentials when they contain URL-reserved
characters. Keep `.env` out of source control. Add only the ITSM, SSO, webhook,
LLM, embedding, or SendGrid settings that the installation uses. SendGrid can
also be configured after deployment by an authenticated administrator under
Settings → SendGrid email; its API key is masked and never returned to the
browser. The complete supported
environment-variable template is [`.env.example`](../.env.example).
Microsoft Entra ID and Okta SSO use provider presets and a callback derived
from `FRONTEND_URL`; follow the [SSO setup guide](sso.md) instead of copying
discovery or callback URLs manually.

There is an intentional two-stage administration caveat. A fresh production
database has no bootstrap administrator, and production startup disables the
seeded demo identities. First deploy in demo mode on a private, controlled
network, sign in as the seeded administrator, and create a separate real
administrator (or configure a reviewed SSO bootstrap).

Before changing `.env`, rotate the password inside the already-initialized
database. This prompt keeps the new value out of shell history and asks for it
twice:

```sh
docker compose exec postgres \
  psql --username tickety --dbname tickety --command '\password tickety'
```

Set `POSTGRES_PASSWORD` and the password in `DATABASE_URL` to that exact new
value, then apply the production configuration above and restart. Do not change
`POSTGRES_USER` or `POSTGRES_DB` on an existing volume unless you separately
migrate the database role or database. The PostgreSQL image uses those three
variables only when initializing an empty data directory; changing them alone
does not modify retained data. Finally, verify that the demo credentials no
longer work before exposing the service.

## Kubernetes with Helm

The supported Kubernetes path is the Helm chart in
[`deploy/helm/tickety`](../deploy/helm/tickety). It creates a migration Job for
every Helm revision; backend and worker Pods wait until the database is at the
Alembic migration head. It deploys the worker as a singleton by default.

Prerequisites: Kubernetes 1.25+, Helm 3.13+ or Helm 4, `kubectl`, and a
registry that the cluster can pull from. For the generic build-and-push path,
Docker Buildx is also required.

```sh
./deploy.sh kubernetes \
  --registry ghcr.io/acme/tickety \
  --namespace tickety \
  --release tickety
```

The script derives an immutable tag, builds and pushes `backend` and `frontend`
images to `<registry>/backend` and `<registry>/frontend`, runs `helm upgrade
--install --wait --wait-for-jobs`, then runs the chart health test. Use
`--tag` to choose the tag. `--skip-build` requires `--tag` and is only for two
images that already exist in the registry. The rendered release is configured
through the chart's [`values.yaml`](../deploy/helm/tickety/values.yaml).
For Entra ID or Okta, use its structured `config.sso` block and the exact
provider steps in the [SSO setup guide](sso.md).

Authenticate Docker to push (`docker login registry.example.com`). For a
private non-ACR registry, create a pull Secret and reference it in the values
file (or use your platform's workload identity integration):

```sh
kubectl create namespace tickety --dry-run=client --output=yaml | kubectl apply -f -
kubectl -n tickety create secret docker-registry tickety-registry \
  --docker-server=registry.example.com \
  --docker-username='<registry-user>' \
  --docker-password='<registry-token>' \
  --dry-run=client --output=yaml | kubectl apply -f -
```

```yaml
imagePullSecrets:
  - name: tickety-registry
```

### Production values

On a fresh database, first install the default demo release in a private
namespace, port-forward it, create a real administrator, and verify that login.
Then copy `deploy/examples/production-values.yaml` to a non-committed values
file, replace its example origin and cluster settings, and upgrade with
`--values tickety-values.yaml`. This is the minimal TLS-ingress shape:

```yaml
config:
  appMode: production
  loginRequired: true
  frontendUrl: https://tickety.nexora.com
  corsAllowOrigins: https://tickety.nexora.com
  cookieSecure: true
  cookieSameSite: lax

ingress:
  enabled: true
  className: nginx
  host: tickety.nexora.com
  tls:
    - hosts: [tickety.nexora.com]
      secretName: tickety-tls

postgresql:
  persistence:
    storageClass: managed-csi
    size: 20Gi

secrets: {}
# Add credentials only for enabled integrations, preferably through
# existingSecret and a secret manager.
```

`config.extra` accepts non-secret settings such as `ITSM_PROVIDER` and
`SYNC_INTERVAL_SECONDS`; use `secrets` for credentials. Production sidecar
deployments should set `ITSM_PROVIDER: freshservice`; the integration only
imports provider data and never sends ticket mutations back.

For a public IP instead of an ingress, set
`frontend.service.type: LoadBalancer`, set `config.frontendUrl` to the final
public origin, and set `config.corsAllowOrigins` to that exact origin. Configure
DNS and TLS outside the chart when using LoadBalancer.

### Secrets and external PostgreSQL

The chart either manages its Secret from `secrets` and database values or reads
an existing Secret named by `existingSecret`. An existing Secret must contain
`DATABASE_URL` and, when the chart's PostgreSQL is enabled, `POSTGRES_PASSWORD`.
It can contain provider and integration credentials too. For example:

```sh
kubectl -n tickety create secret generic tickety-production \
  --from-literal=DATABASE_URL='postgresql+psycopg2://tickety:<url-encoded-password>@db.example.net:5432/tickety' \
  --from-literal=FOUNDRY_API_KEY='<foundry-key>' \
  --from-literal=FOUNDRY_API_BASE='https://<resource>.services.ai.azure.com/openai/v1' \
  --from-literal=DEFAULT_MODEL='foundry/<deployment-name>' \
  --from-literal=LLM_ALLOWED_PROVIDER_HOSTS='<resource>.services.ai.azure.com'
```

Use it with an external PostgreSQL service:

```yaml
existingSecret: tickety-production
postgresql:
  enabled: false
```

After the secret manager rotates an `existingSecret`, update the non-secret
`existingSecretRolloutToken` in the Helm values (for example, with the rotation
timestamp or secret-manager version) and run `helm upgrade`. Kubernetes does
not restart Pods solely because an `envFrom` Secret changes; this token changes
the backend and worker Pod templates without the chart reading or hashing the
external Secret.

Alternatively, with a chart-managed Secret, set `postgresql.enabled: false`
and supply `postgresql.externalDatabaseUrl`. The external database must be
PostgreSQL reachable from backend, worker, and migration pods. If embeddings
are enabled, it must support pgvector. When NetworkPolicy is enabled, add a
narrow rule in `networkPolicy.additionalEgress` for an external/private
database or private AI/ITSM destination; the default policy permits cluster
DNS, in-chart PostgreSQL, and public HTTPS only. Confirm that the cluster's CNI
actually enforces Kubernetes NetworkPolicy; applying the object alone is not
evidence of enforcement.

### AKS and ACR

The `aks` mode builds both images in Azure Container Registry and installs the
same Helm chart. With an existing AKS cluster and ACR:

```sh
az login
az aks get-credentials --resource-group <resource-group> --name <aks-cluster>
az aks update --resource-group <resource-group> --name <aks-cluster> --attach-acr <acr-name>
./deploy.sh aks --acr <acr-name> --namespace tickety --release tickety
```

`--attach-acr` grants the AKS kubelet identity pull access to the registry;
confirm it before deployment with:

```sh
az aks check-acr --resource-group <resource-group> --name <aks-cluster> --acr <acr-name>.azurecr.io
```

The script resolves the ACR login server, builds
`<acr>.azurecr.io/tickety/backend:<tag>` and
`<acr>.azurecr.io/tickety/frontend:<tag>` using `az acr build`, and passes
those image references to Helm. The AKS commands follow the current Azure CLI
reference for [`az aks`](https://learn.microsoft.com/en-us/cli/azure/aks?view=azure-cli-latest)
and [`az acr`](https://learn.microsoft.com/en-us/cli/azure/acr?view=azure-cli-latest).

Port-forward the private default Service to complete the first administrator
bootstrap. Then rerun the same command with `--values tickety-values.yaml` to
enable the production origin, TLS ingress or LoadBalancer, login, and secure
cookies.

Use the AKS storage class available in the cluster for the bundled PostgreSQL
PVC, or use the external PostgreSQL configuration above. Install and configure
an ingress controller/certificate solution before enabling ingress. Otherwise
use a LoadBalancer service and provision DNS/TLS for its assigned address.

## Verify, upgrade, recover, and remove

After each deployment, verify the Helm test and the frontend-proxied readiness
endpoint:

```sh
helm test tickety --namespace tickety --timeout 2m
kubectl get pods,jobs,service,ingress --namespace tickety
kubectl get --raw /api/v1/namespaces/tickety/services/http:tickety-frontend:80/proxy/api/health/ready
```

For this repository's production environment, run the target guard immediately
before and after the rollout. It rejects any namespace that does not own the
`tickety.nexora.com` ingress or whose active frontend hashed asset set is not the
one served by that public origin:

```sh
scripts/verify-production-target.sh --namespace <production-namespace> [--context <production-context>]
```

`tickety.imbell.com` is not a production target and cannot be used as
production deployment evidence.

For a non-default release name, namespace, or frontend service port, replace
the values in the last command. A `ready` response confirms that the frontend
can reach the backend and that the backend can query PostgreSQL. Backend
`/health/live` is process-only; backend `/health/ready` also checks the
database.

Upgrade with the same release, namespace, registry, and production values:

```sh
./deploy.sh kubernetes --registry ghcr.io/acme/tickety --namespace tickety --release tickety --values tickety-values.yaml
```

Migrations are forward-only. Take and verify a PostgreSQL backup before an
upgrade. If an application rollback is needed, first confirm that the older
image is compatible with the migrated schema; otherwise restore the verified
pre-upgrade database backup and deploy a compatible application version. See
[database migration guidance](database-migrations.md) for the recovery policy.

Before removing a release that uses bundled PostgreSQL, retain its generated
database password in a secret manager alongside the verified backup. Helm
removes the chart-managed Secret but Kubernetes retains StatefulSet PVCs; a
later installation must reuse the original password to connect to that data.

To remove a Helm release while retaining the bundled PostgreSQL PVC:

```sh
helm uninstall tickety --namespace tickety
```

The Helm release removal does not itself delete a StatefulSet PVC. Delete the
PVC only after a verified backup and only when intentionally destroying the
data:

```sh
kubectl delete pvc -n tickety data-tickety-postgresql-0
```

For an external database, uninstalling the release never removes the external
database; manage its retention and deletion in that database service.
