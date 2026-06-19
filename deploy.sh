#!/bin/bash
set -e

echo "🛠️ Building targeted images (backend + frontend stages)..."
# Build identifier: short hash of the source tree so each distinct codebase gets a
# stable, identifiable id (the repo isn't a git checkout, so we can't use git
# HEAD). Same source -> same BUILD_SHA; changed source -> different BUILD_SHA.
BUILD_SHA=$(find app Dockerfile requirements.txt deploy.sh -type f 2>/dev/null | sort \
  | xargs shasum -a 256 2>/dev/null | shasum -a 256 | cut -c1-7)
BUILD_SHA=${BUILD_SHA:-local}
BUILD_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "   build sha : $BUILD_SHA"
echo "   build time: $BUILD_TIME"
docker build --target backend  -t tickety-backend:latest  --build-arg BUILD_SHA="$BUILD_SHA" --build-arg BUILD_TIME="$BUILD_TIME" -f Dockerfile .
docker build --target frontend -t tickety-frontend:latest --build-arg BUILD_SHA="$BUILD_SHA" --build-arg BUILD_TIME="$BUILD_TIME" -f Dockerfile .

echo "🚀 Applying Kubernetes manifests..."
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/secrets.yaml
kubectl apply -f k8s/postgres.yaml
kubectl apply -f k8s/backend.yaml
kubectl apply -f k8s/frontend.yaml

# Secrets/env were applied above; roll the pods so they pick up the freshly
# built local images (imagePullPolicy: Never means k8s won't re-pull, and the
# tag didn't change, so an explicit rollout is required).
echo "♻️ Rolling out backend and frontend to load new images..."
kubectl rollout restart deployment/backend  -n tickety
kubectl rollout restart deployment/frontend -n tickety

echo "⏳ Waiting for rollouts to finish..."
kubectl rollout status deployment/backend  -n tickety --timeout=180s
kubectl rollout status deployment/frontend -n tickety --timeout=180s

echo "✅ Deployment complete!"
echo "🔍 Checking pod status..."
kubectl get pods -n tickety
echo ""
echo "🌐 Frontend: http://localhost:3000"
echo "🔌 Backend API: http://localhost:8000"