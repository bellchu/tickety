#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CHART_DIR="$ROOT_DIR/deploy/helm/tickety"
REQUIRE_DOCKER=false
REQUIRE_HELM=false
REQUIRE_KUBECTL=false
REQUIRE_KUBECTL_CLUSTER=false
REQUIRE_YAML=false

usage() {
  cat <<'EOF'
Usage: scripts/validate-deployment.sh [options]

Validate the OCI Kubernetes production release path and local Compose configuration.
Unavailable optional tools are skipped unless explicitly required.

Options:
  --require-docker          Fail unless Docker Compose v2 is available.
  --require-helm            Fail unless Helm is available.
  --require-kubectl         Fail unless kubectl is available.
  --require-kubectl-cluster Fail unless kubectl can reach a cluster.
  --require-yaml             Fail unless Python with PyYAML is available.
  -h, --help                 Show this help text.
EOF
}

require_or_skip() {
  local required=$1
  local tool=$2

  if command -v "$tool" >/dev/null 2>&1; then
    return 0
  fi
  if [[ $required == true ]]; then
    echo "Required tool is unavailable: $tool" >&2
    exit 1
  fi
  echo "Skipping $tool validation: tool is unavailable."
  return 1
}

while (($#)); do
  case "$1" in
    --require-docker) REQUIRE_DOCKER=true ;;
    --require-helm) REQUIRE_HELM=true ;;
    --require-kubectl) REQUIRE_KUBECTL=true ;;
    --require-kubectl-cluster)
      REQUIRE_KUBECTL=true
      REQUIRE_KUBECTL_CLUSTER=true
      ;;
    --require-yaml) REQUIRE_YAML=true ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
done

echo "Checking deployment shell scripts..."
bash -n   "$ROOT_DIR/deploy.sh"   "$ROOT_DIR/scripts/validate-deployment.sh"   "$ROOT_DIR/scripts/verify-production-target.sh"   "$ROOT_DIR/scripts/deploy-dev-microk8s.sh"   "$ROOT_DIR/scripts/validate-dev-deployment.sh"   "$ROOT_DIR/deploy/dev-microk8s/install-release.sh"   "$ROOT_DIR/deploy/dev-microk8s/remote-release.sh"   "$ROOT_DIR/deploy/dev-microk8s/verify.sh"
backend_stage_line=$(grep -nF 'FROM python:3.11.16-slim AS backend' \
  "$ROOT_DIR/Dockerfile" | cut -d: -f1)
frontend_builder_line=$(grep -nF 'FROM node:24.19.0-alpine AS frontend-builder' \
  "$ROOT_DIR/Dockerfile" | cut -d: -f1)
[[ $backend_stage_line =~ ^[0-9]+$ \
  && $frontend_builder_line =~ ^[0-9]+$ \
  && $backend_stage_line -lt $frontend_builder_line ]] || {
  echo "A targeted backend image build must not execute the frontend stage." >&2
  exit 1
}

echo "Checking production target guard..."
"$ROOT_DIR/scripts/verify-production-target.sh" --self-test
grep -Fq -- '--host HOST' "$ROOT_DIR/scripts/verify-production-target.sh"
grep -Fq 'tickety.situ.io' "$ROOT_DIR/deploy/examples/production-values.yaml"
if require_or_skip "$REQUIRE_DOCKER" docker; then
  if ! docker compose version >/dev/null 2>&1; then
    if [[ $REQUIRE_DOCKER == true ]]; then
      echo "Docker Compose 2.24 or later is required." >&2
      exit 1
    fi
    echo "Skipping Docker validation: Docker Compose v2 is unavailable."
  else
    echo "Checking local Docker Compose configuration..."
    docker compose --project-directory "$ROOT_DIR" \
      -f "$ROOT_DIR/docker-compose.yml" config --quiet
    if ! grep -Eq '^[[:space:]]*reverse_proxy[[:space:]]+frontend:3000[[:space:]]*$' \
      "$ROOT_DIR/deploy/local-tunnel/Caddyfile"; then
      echo "Local tunnel must forward to frontend:3000." >&2
      exit 1
    fi
  fi
fi

if require_or_skip "$REQUIRE_HELM" helm; then
  [[ -f "$CHART_DIR/Chart.yaml" ]] || {
    echo "Helm chart is missing: $CHART_DIR" >&2
    exit 1
  }
  echo "Linting Helm chart..."
  helm lint --strict --kube-version 1.25.0 "$CHART_DIR"
  temporary_dir=$(mktemp -d)
  cleanup() { rm -rf -- "$temporary_dir"; }
  trap cleanup EXIT
  helm template tickety "$CHART_DIR" --namespace tickety --kube-version 1.25.0 \
    --values "$ROOT_DIR/deploy/examples/production-values.yaml" >"$temporary_dir/production.yaml"
  helm template tickety "$CHART_DIR" --namespace tickety --kube-version 1.25.0 \
    --set ingress.enabled=true --set ingress.host=tickety.example.test >"$temporary_dir/ingress.yaml"
  helm template tickety "$CHART_DIR" --namespace tickety --kube-version 1.25.0 \
    --set backup.enabled=true >"$temporary_dir/backup.yaml"
  echo "Helm chart rendering passed."
fi

yaml_python=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import yaml' >/dev/null 2>&1; then
    yaml_python=$candidate
    break
  fi
done
if [[ -n $yaml_python && -n ${temporary_dir:-} ]]; then
  "$yaml_python" - "$temporary_dir/production.yaml" "$temporary_dir/ingress.yaml" "$temporary_dir/backup.yaml" <<'PY'
from pathlib import Path
import sys
import yaml

for filename in sys.argv[1:]:
    documents = list(yaml.safe_load_all(Path(filename).read_text()))
    if not documents:
        raise SystemExit(f"empty rendered chart: {filename}")
    for index, document in enumerate(documents, start=1):
        if not isinstance(document, dict):
            raise SystemExit(f"{filename}:{index}: resource is not a mapping")
        if not {"apiVersion", "kind", "metadata"} <= document.keys():
            raise SystemExit(f"{filename}:{index}: missing Kubernetes resource fields")
print("Rendered Kubernetes YAML structure passed.")
PY
elif [[ $REQUIRE_YAML == true ]]; then
  echo "Required YAML validator is unavailable: install PyYAML." >&2
  exit 1
fi

if require_or_skip "$REQUIRE_KUBECTL" kubectl; then
  if kubectl version --request-timeout=5s --output=json >/dev/null 2>&1; then
    echo "kubectl can reach the selected cluster: $(kubectl config current-context)"
  elif [[ $REQUIRE_KUBECTL_CLUSTER == true ]]; then
    echo "A reachable OCI Kubernetes cluster is required." >&2
    exit 1
  else
    echo "Skipping kubectl cluster validation: no reachable cluster."
  fi
fi

echo "OCI production deployment validation passed."
