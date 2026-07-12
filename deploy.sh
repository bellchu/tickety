#!/bin/bash
set -euo pipefail

echo "🛠️ Building targeted images (backend + frontend stages)..."
# Build identifier: short hash of the source tree so each distinct codebase gets a
# stable, identifiable id (the repo isn't a git checkout, so we can't use git
# HEAD). Same source -> same BUILD_SHA; changed source -> different BUILD_SHA.
BUILD_SHA=$(find app migrations Dockerfile requirements.txt requirements.lock alembic.ini deploy.sh -type f 2>/dev/null | sort \
  | xargs shasum -a 256 2>/dev/null | shasum -a 256 | cut -c1-7)
BUILD_SHA=${BUILD_SHA:-local}
BUILD_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "   build sha : $BUILD_SHA"
echo "   build time: $BUILD_TIME"
docker build --target backend  -t tickety-backend:latest  --build-arg BUILD_SHA="$BUILD_SHA" --build-arg BUILD_TIME="$BUILD_TIME" -f Dockerfile .
docker build --target frontend -t tickety-frontend:latest --build-arg BUILD_SHA="$BUILD_SHA" --build-arg BUILD_TIME="$BUILD_TIME" -f Dockerfile .

echo "🚀 Applying Kubernetes manifests..."
kubectl apply -f k8s/namespace.yaml
if ! kubectl get secret tickety-secrets -n tickety >/dev/null 2>&1; then
  echo "❌ Missing Secret tickety/tickety-secrets." >&2
  echo "   Create it using k8s/README.md before deploying." >&2
  exit 1
fi
kubectl apply -f k8s/postgres.yaml
kubectl apply -n tickety -f k8s/network-policy.yaml
bash k8s/verify-network-policy.sh tickety

echo "🗄️ Applying database migrations..."
# Jobs have immutable pod templates and a completed Job will not rerun. Replace
# only this task-owned Job, then require successful completion before workloads
# using the new schema are applied or restarted.
kubectl delete job tickety-migrate -n tickety --ignore-not-found=true
kubectl apply -f k8s/migrate.yaml
if ! kubectl wait --for=condition=complete job/tickety-migrate -n tickety --timeout=300s; then
  echo "❌ Database migration failed; workloads were not rolled out." >&2
  echo "   Inspect: kubectl describe job/tickety-migrate -n tickety" >&2
  exit 1
fi

kubectl apply -f k8s/backend.yaml
kubectl apply -f k8s/frontend.yaml

# Secrets/env were applied above; roll the pods so they pick up the freshly
# built local images (imagePullPolicy: Never means k8s won't re-pull, and the
# tag didn't change, so an explicit rollout is required).
echo "♻️ Rolling out backend, worker, and frontend to load new images..."
kubectl rollout restart deployment/backend  -n tickety
kubectl rollout restart deployment/backend-worker -n tickety
kubectl rollout restart deployment/frontend -n tickety

echo "⏳ Waiting for rollouts to finish..."
kubectl rollout status deployment/backend  -n tickety --timeout=180s
kubectl rollout status deployment/backend-worker -n tickety --timeout=180s
kubectl rollout status deployment/frontend -n tickety --timeout=180s

echo "✅ Deployment complete!"
echo "🔍 Checking pod status..."
kubectl get pods -n tickety
echo ""
echo "🌐 Frontend: http://localhost:17000"
echo "🔌 Backend API: http://localhost:8000"
