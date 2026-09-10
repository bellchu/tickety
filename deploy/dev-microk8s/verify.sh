#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
: "${TICKETY_DEV_NAMESPACE:?set TICKETY_DEV_NAMESPACE}"
: "${TICKETY_DEV_PUBLIC_HOST:?set TICKETY_DEV_PUBLIC_HOST}"
: "${TICKETY_DEV_REGISTRY:?set TICKETY_DEV_REGISTRY}"
readonly NAMESPACE=$TICKETY_DEV_NAMESPACE
readonly PUBLIC_URL=https://$TICKETY_DEV_PUBLIC_HOST
readonly REGISTRY=$TICKETY_DEV_REGISTRY
KUBECTL=(microk8s kubectl)

die() { echo "Dev verification failed: $*" >&2; exit 1; }

(($# == 2)) || die "usage: verify.sh FULL_SHA SHORT_SHA"
readonly FULL_SHA=$1 SHORT_SHA=$2
[[ $FULL_SHA =~ ^[0-9a-f]{40}$ ]] || die "invalid full Git SHA"
[[ $SHORT_SHA =~ ^[0-9a-f]{12}$ && $FULL_SHA == "$SHORT_SHA"* ]] || die "invalid short Git SHA"
readonly BACKEND_IMAGE=$REGISTRY/tickety-backend:dev-$SHORT_SHA
readonly FRONTEND_IMAGE=$REGISTRY/tickety-frontend:dev-$SHORT_SHA

[[ $(id -u) == 0 ]] || die "verifier must run through sudo"
[[ $(uname -m) == x86_64 ]] || die "dev host must be x86_64"
systemctl is-active --quiet cloudflared || die "cloudflared is not active"
microk8s status --wait-ready >/dev/null

coredns_corefile=$("${KUBECTL[@]}" -n kube-system get configmap coredns -o jsonpath='{.data.Corefile}')
printf '%s' "$coredns_corefile" | \
  python3 "$ROOT_DIR/deploy/dev-microk8s/ensure-coredns-prefer-udp.py" --check
dns_service_ip=$("${KUBECTL[@]}" -n kube-system get service kube-dns -o jsonpath='{.spec.clusterIP}')
dns_probe=$(dig +tcp +time=3 +tries=1 @"$dns_service_ip" iana.org A)
grep -Fq 'status: NOERROR' <<<"$dns_probe" || die "CoreDNS TCP-client to UDP-upstream fallback failed"
grep -Eq '[[:space:]]IN[[:space:]]+A[[:space:]]+[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' <<<"$dns_probe" || \
  die "CoreDNS fallback returned no public IPv4 answer"

for deployment in backend backend-worker; do
  dns_options=$("${KUBECTL[@]}" -n "$NAMESPACE" get deployment "$deployment" \
    -o jsonpath='{.spec.template.spec.dnsConfig.options[*].name}')
  grep -qw edns0 <<<"$dns_options" || die "$deployment does not advertise EDNS0"
  directory_env=$("${KUBECTL[@]}" -n "$NAMESPACE" get deployment "$deployment" \
    -o jsonpath='{range .spec.template.spec.containers[*].env[*]}{.name}={.value}{"\n"}{end}')
  for expected_directory_env in \
    DIRECTORY_PEOPLE_READ_ENABLED=true \
    DIRECTORY_PEOPLE_WRITE_ENABLED=true \
    REMOTE_AGENT_TEAM_ELIGIBLE=true; do
    grep -Fxq "$expected_directory_env" <<<"$directory_env" || \
      die "$deployment is missing dev directory capability $expected_directory_env"
  done
done

ingress_hosts=$("${KUBECTL[@]}" -n "$NAMESPACE" get ingress frontend-ingress -o jsonpath='{range .spec.rules[*]}{.host}{"\n"}{end}')
[[ $ingress_hosts == "$TICKETY_DEV_PUBLIC_HOST" ]] || die "ingress host is not the isolated dev hostname"
backend_live=$("${KUBECTL[@]}" -n "$NAMESPACE" get deployment backend -o jsonpath='{.spec.template.spec.containers[?(@.name=="backend")].image}')
worker_live=$("${KUBECTL[@]}" -n "$NAMESPACE" get deployment backend-worker -o jsonpath='{.spec.template.spec.containers[?(@.name=="worker")].image}')
frontend_live=$("${KUBECTL[@]}" -n "$NAMESPACE" get deployment frontend -o jsonpath='{.spec.template.spec.containers[?(@.name=="frontend")].image}')
[[ $backend_live == "$BACKEND_IMAGE" && $worker_live == "$BACKEND_IMAGE" ]] || die "backend images do not match the expected dev build"
[[ $frontend_live == "$FRONTEND_IMAGE" ]] || die "frontend image does not match the expected dev build"

for deployment in backend backend-worker frontend; do
  desired=$("${KUBECTL[@]}" -n "$NAMESPACE" get deployment "$deployment" -o jsonpath='{.spec.replicas}')
  available=$("${KUBECTL[@]}" -n "$NAMESPACE" get deployment "$deployment" -o jsonpath='{.status.availableReplicas}')
  [[ -n $desired && $desired == "$available" ]] || die "$deployment is not fully available"
done

backend_dns_verified=false
for dns_attempt in 1 2 3; do
  if backend_container_id=$("${KUBECTL[@]}" -n "$NAMESPACE" get pods \
      -l app=backend --field-selector=status.phase=Running -o json | \
      python3 "$ROOT_DIR/deploy/dev-microk8s/select-ready-container.py" \
        --image "$BACKEND_IMAGE" --container backend); then
    if dns_probe_output=$(microk8s ctr tasks exec \
        --exec-id "tickety-dns-verify-$SHORT_SHA-$$-$dns_attempt" \
        "$backend_container_id" python -c \
        'import os, socket; from urllib.parse import urlparse; from app.backend import settings; settings.load_settings_into_env(); host=urlparse(os.environ.get("FOUNDRY_API_BASE", "")).hostname or "iana.org"; addresses={item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}; assert addresses; print("backend provider DNS resolution passed")' 2>&1); then
      printf '%s\n' "$dns_probe_output"
      backend_dns_verified=true
      break
    fi
  fi
  sleep 1
done
[[ $backend_dns_verified == true ]] || die "provider DNS probe could not reach the current ready backend container"

readiness=$(curl --fail --silent --show-error --max-time 20 "$PUBLIC_URL/api/health/ready")
version=$(curl --fail --silent --show-error --max-time 20 "$PUBLIC_URL/api/version")
python3 - "$readiness" "$version" "$SHORT_SHA" <<'PY'
import json
import sys

readiness = json.loads(sys.argv[1])
version = json.loads(sys.argv[2])
expected = sys.argv[3]
if readiness != {"status": "ready", "checks": {"database": "ok"}}:
    raise SystemExit(f"unexpected readiness evidence: {readiness!r}")
if version.get("component") != "backend" or version.get("build_sha") != expected:
    raise SystemExit(f"unexpected version evidence: {version!r}")
if not version.get("build_time") or not version.get("version"):
    raise SystemExit("version evidence is incomplete")
PY
curl --fail --silent --show-error --max-time 20 --output /dev/null \
  "$PUBLIC_URL/_next/static/$SHORT_SHA/_buildManifest.js"

echo "Dev deployment verified: source=$FULL_SHA backend=$BACKEND_IMAGE frontend=$FRONTEND_IMAGE"
echo "CoreDNS transport evidence: TCP client query resolved through UDP-only upstream."
echo "Backend DNS evidence: configured provider hostname resolved with EDNS0."
echo "Public readiness evidence: $readiness"
echo "Public version evidence: $version"
