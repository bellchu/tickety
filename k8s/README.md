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
  --from-literal=WEBHOOK_SECRET='<generate-a-random-secret>' \
  --from-literal=ITSM_PROVIDER='jira' \
  --from-literal=SYNC_INTERVAL_SECONDS=60
```

Add only the provider and AI credentials required by the deployment. Prefer
an external secret controller in shared or production clusters. Never commit
rendered Secret manifests or plaintext credentials.

The database password in `DATABASE_URL` must be URL-encoded and must match
`POSTGRES_PASSWORD`. Apply the remaining manifests only after the Secret
exists.
