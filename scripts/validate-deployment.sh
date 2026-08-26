#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
REQUIRE_DOCKER=false

usage() {
  cat <<'EOF'
Usage: scripts/validate-deployment.sh [--require-docker]

Validate the only supported Tickety OPS Tower production release path: Docker Compose to
https://tickety.nexora.com through the fixed local Cloudflare Tunnel mapping.

Options:
  --require-docker  Fail unless Docker Compose v2 is available.
  -h, --help        Show this help text.
EOF
}

while (($#)); do
  case "$1" in
    --require-docker) REQUIRE_DOCKER=true ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
done

if [[ -n ${DOCKER_HOST:-} || -n ${DOCKER_CONTEXT:-} ]]; then
  echo "Deployment validation rejects DOCKER_HOST and DOCKER_CONTEXT overrides." >&2
  exit 1
fi

echo "Checking production shell scripts..."
bash -n \
  "$ROOT_DIR/deploy.sh" \
  "$ROOT_DIR/scripts/validate-deployment.sh" \
  "$ROOT_DIR/scripts/verify-compose-production.sh"

echo "Checking production target regression guards..."
"$ROOT_DIR/scripts/verify-compose-production.sh" --self-test

echo "Checking Docker production release gate wiring..."
if [[ $(grep -Fc '"$ROOT_DIR/scripts/verify-compose-production.sh" --mapping-only' \
  "$ROOT_DIR/deploy.sh") -lt 2 ]]; then
  echo "Docker deployment must verify the fixed production mapping before build and rollout." >&2
  exit 1
fi
if ! grep -Fq -- '--expected-full-sha "$build_full_sha"' "$ROOT_DIR/deploy.sh" || \
  ! grep -Fq -- '--expected-short-sha "$build_sha"' "$ROOT_DIR/deploy.sh"; then
  echo "Docker deployment must verify the expected full and short Git SHA after rollout." >&2
  exit 1
fi
if grep -Eq 'deploy_(kubernetes|aks)|MODE == (kubernetes|aks)|helm upgrade|kubectl apply|az acr build' \
  "$ROOT_DIR/deploy.sh"; then
  echo "deploy.sh must not expose a production path outside Docker Compose." >&2
  exit 1
fi
if "$ROOT_DIR/deploy.sh" kubernetes >/dev/null 2>&1; then
  echo "deploy.sh unexpectedly accepted a Kubernetes production mode." >&2
  exit 1
fi
for docker_override in DOCKER_HOST DOCKER_CONTEXT; do
  if env "$docker_override=tcp://127.0.0.1:9" \
    "$ROOT_DIR/scripts/verify-compose-production.sh" --mapping-only >/dev/null 2>&1; then
    echo "Production verifier accepted forbidden $docker_override override." >&2
    exit 1
  fi
done

echo "Checking Docker build-context exclusions..."
for pattern in '.env' '.env.*' 'backups/' '*.dump' '*.backup' '*.bak' '*.sql' '*.sql.gz'; do
  if ! grep -Fqx -- "$pattern" "$ROOT_DIR/.dockerignore"; then
    echo ".dockerignore must exclude $pattern" >&2
    exit 1
  fi
done

if ! command -v docker >/dev/null 2>&1; then
  if [[ $REQUIRE_DOCKER == true ]]; then
    echo "Required tool is unavailable: docker" >&2
    exit 1
  fi
  echo "Skipping Compose validation: docker is unavailable."
  echo "Deployment validation passed."
  exit 0
fi
if ! docker compose version >/dev/null 2>&1; then
  if [[ $REQUIRE_DOCKER == true ]]; then
    echo "Docker Compose 2.24 or later is required (run it as 'docker compose')." >&2
    exit 1
  fi
  echo "Skipping Compose validation: Docker Compose v2 is unavailable."
  echo "Deployment validation passed."
  exit 0
fi

echo "Checking Docker Compose configuration..."
docker compose --project-directory "$ROOT_DIR" \
  -f "$ROOT_DIR/docker-compose.yml" config --quiet

python_command=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    python_command=$candidate
    break
  fi
done
if [[ -z $python_command ]]; then
  echo "Python is required to validate the rendered Compose topology." >&2
  exit 1
fi

docker compose --project-directory "$ROOT_DIR" \
  -f "$ROOT_DIR/docker-compose.yml" config --format json |
  "$python_command" -c '
import json
import sys

model = json.load(sys.stdin)
if model.get("name") != "tickety":
    raise SystemExit("Compose production project name must be tickety")
services = model["services"]
expected = {"postgres", "migrate", "backend", "worker", "frontend", "tunnel-proxy"}
if set(services) != expected:
    raise SystemExit(f"Compose services differ from the fixed topology: {sorted(services)}")
for name in ("migrate", "backend", "worker"):
    if services[name].get("image") != "tickety-backend:latest":
        raise SystemExit(f"{name} must use tickety-backend:latest")
if services["frontend"].get("image") != "tickety-frontend:latest":
    raise SystemExit("frontend must use tickety-frontend:latest")
for name, service in services.items():
    if name not in {"frontend", "tunnel-proxy"} and service.get("ports"):
        raise SystemExit(f"{name} must not publish host ports")
frontend_ports = services["frontend"].get("ports") or []
if len(frontend_ports) != 1:
    raise SystemExit("frontend must publish exactly one host port")
frontend_port = frontend_ports[0]
if (
    frontend_port.get("mode") != "ingress"
    or frontend_port.get("target") != 3000
    or frontend_port.get("protocol") != "tcp"
    or frontend_port.get("host_ip") != "127.0.0.1"
):
    raise SystemExit("frontend host port must bind TCP 3000 to IPv4 loopback only")
expected_tunnel_port = {
    "mode": "ingress",
    "target": 443,
    "published": "443",
    "protocol": "tcp",
    "host_ip": "127.0.0.1",
}
if (services["tunnel-proxy"].get("ports") or []) != [expected_tunnel_port]:
    raise SystemExit("tunnel-proxy must bind host TCP 443 to IPv4 loopback only")
if services["tunnel-proxy"]["depends_on"]["frontend"]["condition"] != "service_healthy":
    raise SystemExit("tunnel-proxy must wait for the healthy frontend")
for name in ("backend", "worker"):
    if services[name]["depends_on"]["migrate"]["condition"] != "service_completed_successfully":
        raise SystemExit(f"{name} must wait for successful migrations")
if services["worker"]["environment"].get("TICKETY_PROCESS_ROLE") != "worker":
    raise SystemExit("worker process role is missing")
print("Validated Docker Compose service topology.")
'

echo "Checking DATABASE_URL routing-override rejection..."
test_password=local-production-gate-test-password-0000000000000000000000000000
for unsafe_database_url in \
  "postgresql+psycopg2://tickety:${test_password}@postgres:5432/tickety?host=outside.invalid&port=6543" \
  "postgresql+psycopg2://tickety:${test_password}@postgres:5432/tickety#host=outside.invalid"; do
  if POSTGRES_USER=tickety \
    POSTGRES_PASSWORD="$test_password" \
    POSTGRES_DB=tickety \
    DATABASE_URL="$unsafe_database_url" \
    "$ROOT_DIR/scripts/verify-compose-production.sh" --mapping-only >/dev/null 2>&1; then
    echo "Production verifier accepted a DATABASE_URL routing override." >&2
    exit 1
  fi
done
unset test_password unsafe_database_url

if ! grep -Eq '^[[:space:]]*reverse_proxy[[:space:]]+frontend:3000[[:space:]]*$' \
  "$ROOT_DIR/deploy/local-tunnel/Caddyfile"; then
  echo "tunnel-proxy must forward to frontend:3000" >&2
  exit 1
fi

echo "Deployment validation passed."
