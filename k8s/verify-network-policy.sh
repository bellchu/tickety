#!/bin/bash
set -euo pipefail

NAMESPACE=${1:-tickety}
TARGET=tickety-egress-policy-target
CONTROL=tickety-egress-policy-control
RESTRICTED=tickety-egress-policy-restricted

cleanup() {
  kubectl delete pod "$TARGET" "$CONTROL" "$RESTRICTED" \
    -n "$NAMESPACE" --ignore-not-found=true --wait=false >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup

kubectl run "$TARGET" -n "$NAMESPACE" \
  --image=tickety-backend:latest --image-pull-policy=Never \
  --labels=app=egress-policy-target --restart=Never \
  --command -- python -m http.server 18080
kubectl wait -n "$NAMESPACE" --for=condition=Ready "pod/$TARGET" --timeout=60s
TARGET_IP=$(kubectl get pod "$TARGET" -n "$NAMESPACE" -o jsonpath='{.status.podIP}')

# Prove the target is reachable without the selected backend policy.
kubectl run "$CONTROL" -n "$NAMESPACE" --rm --attach --restart=Never \
  --image=tickety-backend:latest --image-pull-policy=Never \
  --labels=app=egress-policy-control \
  --command -- python -c \
  "import socket; socket.create_connection(('$TARGET_IP', 18080), 3).close()"

# The same reachable private pod must be blocked for a backend-selected pod.
if kubectl run "$RESTRICTED" -n "$NAMESPACE" --rm --attach --restart=Never \
  --image=tickety-backend:latest --image-pull-policy=Never \
  --labels=app=backend \
  --command -- python -c \
  "import socket; socket.create_connection(('$TARGET_IP', 18080), 3).close()"; then
  echo "NetworkPolicy is not enforced: backend pod reached private canary." >&2
  exit 1
fi
kubectl delete pod "$RESTRICTED" -n "$NAMESPACE" \
  --ignore-not-found=true --wait=true >/dev/null 2>&1 || true

# Selected pods must retain DNS and public HTTPS access.
kubectl run "$RESTRICTED" -n "$NAMESPACE" --rm --attach --restart=Never \
  --image=tickety-backend:latest --image-pull-policy=Never \
  --labels=app=backend \
  --command -- python -c \
  "import urllib.request; urllib.request.urlopen('https://example.com', timeout=10).read(1)"

echo "NetworkPolicy enforcement verified in namespace $NAMESPACE."
