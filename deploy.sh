#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CHART_DIR="$ROOT_DIR/deploy/helm/tickety"

usage() {
  cat <<'EOF'
Usage:
  ./deploy.sh docker
  ./deploy.sh kubernetes --registry REGISTRY_PREFIX [options]

Docker options:
  No flags are required. Configure optional settings in .env.

Kubernetes options:
  --registry PREFIX   Registry path, for example registry.example.com/tickety
  --tag TAG           Immutable image tag (default: Git SHA plus timestamp)
  --host HOST         Public production hostname (required)
  --namespace NAME    Kubernetes namespace (default: tickety)
  --release NAME      Helm release name (default: tickety)
  --values FILE       Additional Helm values file
  --platform VALUE    Buildx target platform (default: linux/amd64)
  --timeout VALUE     Helm timeout (default: 10m)
  --skip-build        Deploy images that already exist in the registry

Examples:
  ./deploy.sh docker
  ./deploy.sh kubernetes --registry registry.example.com/tickety \
    --host tickety.example.com \
    --values deploy/examples/production-values.yaml
EOF
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required command not found: $1" >&2
    exit 1
  fi
}

validate_kubernetes_name() {
  local value=$1
  local label=$2
  local max_length=${3:-63}
  if [[ ! $value =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]] || ((${#value} > max_length)); then
    echo "$label must be a valid DNS label with at most $max_length characters: $value" >&2
    exit 1
  fi
}

source_sha() {
  if command -v git >/dev/null 2>&1 && git -C "$ROOT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git -C "$ROOT_DIR" rev-parse --short=12 HEAD
  else
    printf 'local'
  fi
}

deploy_docker() {
  require_command docker
  if ! docker compose version >/dev/null 2>&1; then
    echo "Docker Compose 2.24 or later is required (run it as 'docker compose')." >&2
    exit 1
  fi

  docker compose --project-directory "$ROOT_DIR" \
    -f "$ROOT_DIR/docker-compose.yml" config --quiet
  docker compose --project-directory "$ROOT_DIR" \
    -f "$ROOT_DIR/docker-compose.yml" up --detach --build --wait
  frontend_binding=$(docker compose --project-directory "$ROOT_DIR" \
    -f "$ROOT_DIR/docker-compose.yml" port frontend 3000)
  echo "Tickety local Compose environment is ready on $frontend_binding"
}

MODE=${1:-}
if [[ -z $MODE || $MODE == "-h" || $MODE == "--help" ]]; then
  usage
  exit 0
fi
shift

if [[ $MODE == docker ]]; then
  if (($#)); then
    echo "The docker mode does not accept command-line options; use .env." >&2
    exit 1
  fi
  deploy_docker
  exit 0
fi

if [[ $MODE != kubernetes ]]; then
  echo "Unsupported deployment mode: $MODE" >&2
  usage >&2
  exit 1
fi

REGISTRY_PREFIX=""
IMAGE_TAG=""
TAG_WAS_PROVIDED=false
NAMESPACE=tickety
RELEASE=tickety
VALUES_FILE=""
PRODUCTION_HOST=""
PLATFORM=linux/amd64
HELM_TIMEOUT=10m
SKIP_BUILD=false

while (($#)); do
  case "$1" in
    --registry)
      REGISTRY_PREFIX=${2:?--registry requires a value}
      shift 2
      ;;
    --tag)
      IMAGE_TAG=${2:?--tag requires a value}
      TAG_WAS_PROVIDED=true
      shift 2
      ;;
    --namespace)
      NAMESPACE=${2:?--namespace requires a value}
      shift 2
      ;;
    --host)
      PRODUCTION_HOST=${2:?--host requires a value}
      shift 2
      ;;
    --release)
      RELEASE=${2:?--release requires a value}
      shift 2
      ;;
    --values)
      VALUES_FILE=${2:?--values requires a value}
      shift 2
      ;;
    --platform)
      PLATFORM=${2:?--platform requires a value}
      shift 2
      ;;
    --timeout)
      HELM_TIMEOUT=${2:?--timeout requires a value}
      shift 2
      ;;
    --skip-build)
      SKIP_BUILD=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

validate_kubernetes_name "$NAMESPACE" Namespace
validate_kubernetes_name "$RELEASE" Release 53

if [[ -n $VALUES_FILE && ! -r $VALUES_FILE ]]; then
  echo "Values file is not readable: $VALUES_FILE" >&2
  exit 1
fi
if [[ -z $REGISTRY_PREFIX ]]; then
  echo "Kubernetes mode requires --registry REGISTRY_PREFIX." >&2
  exit 1
fi
if [[ -z $PRODUCTION_HOST || ! $PRODUCTION_HOST =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])$ ]]; then
  echo "Kubernetes mode requires --host with a lowercase DNS hostname." >&2
  exit 1
fi

BUILD_SHA=$(source_sha)
BUILD_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ)
if [[ -z $IMAGE_TAG ]]; then
  IMAGE_TAG="${BUILD_SHA}-$(date -u +%Y%m%d%H%M%S)"
fi
if [[ $SKIP_BUILD == true && $TAG_WAS_PROVIDED == false ]]; then
  echo "--skip-build requires --tag so the existing images are unambiguous." >&2
  exit 1
fi
if [[ ! $IMAGE_TAG =~ ^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$ ]]; then
  echo "Invalid container image tag: $IMAGE_TAG" >&2
  exit 1
fi

require_command kubectl
require_command helm
KUBE_CONTEXT=$(kubectl config current-context)
kubectl cluster-info >/dev/null
echo "OCI Kubernetes context selected: $KUBE_CONTEXT"

REGISTRY_PREFIX=${REGISTRY_PREFIX%/}
if [[ -z $REGISTRY_PREFIX || $REGISTRY_PREFIX =~ [[:space:]] ]]; then
  echo "Registry prefix must be non-empty and contain no whitespace." >&2
  exit 1
fi
BACKEND_REPOSITORY="$REGISTRY_PREFIX/backend"
FRONTEND_REPOSITORY="$REGISTRY_PREFIX/frontend"

HELM_VALUE_ARGS=()
if [[ -n $VALUES_FILE ]]; then
  HELM_VALUE_ARGS+=(--values "$VALUES_FILE")
fi
HELM_VALUE_ARGS+=(
  --set-string "config.frontendUrl=https://$PRODUCTION_HOST"
  --set-string "config.corsAllowOrigins=https://$PRODUCTION_HOST"
  --set-string "ingress.host=$PRODUCTION_HOST"
  --set-string "backend.image.repository=$BACKEND_REPOSITORY"
  --set-string "backend.image.tag=$IMAGE_TAG"
  --set-string "frontend.image.repository=$FRONTEND_REPOSITORY"
  --set-string "frontend.image.tag=$IMAGE_TAG"
)

echo "Validating Helm configuration..."
helm lint --strict --kube-version 1.25.0 "$CHART_DIR" "${HELM_VALUE_ARGS[@]}"
helm template "$RELEASE" "$CHART_DIR" --namespace "$NAMESPACE" \
  --kube-version 1.25.0 "${HELM_VALUE_ARGS[@]}" >/dev/null

if [[ $SKIP_BUILD == false ]]; then
  require_command docker
  if ! docker buildx version >/dev/null 2>&1; then
    echo "Docker Buildx is required to build portable Kubernetes images." >&2
    exit 1
  fi
  echo "Building and pushing OCI production images..."
  docker buildx build --platform "$PLATFORM" --target backend --push \
    --tag "$BACKEND_REPOSITORY:$IMAGE_TAG" \
    --build-arg "BUILD_SHA=$BUILD_SHA" --build-arg "BUILD_TIME=$BUILD_TIME" \
    "$ROOT_DIR"
  docker buildx build --platform "$PLATFORM" --target frontend --push \
    --tag "$FRONTEND_REPOSITORY:$IMAGE_TAG" \
    --build-arg "BUILD_SHA=$BUILD_SHA" --build-arg "BUILD_TIME=$BUILD_TIME" \
    "$ROOT_DIR"
fi

HELM_ARGS=(
  upgrade --install "$RELEASE" "$CHART_DIR"
  --namespace "$NAMESPACE"
  --create-namespace
  "${HELM_VALUE_ARGS[@]}"
  --wait
  --wait-for-jobs
  --timeout "$HELM_TIMEOUT"
)

echo "Deploying Helm release $RELEASE to OCI Kubernetes namespace $NAMESPACE..."
helm "${HELM_ARGS[@]}"
helm test "$RELEASE" --namespace "$NAMESPACE" --timeout 2m
"$ROOT_DIR/scripts/verify-production-target.sh" --host "$PRODUCTION_HOST" --namespace "$NAMESPACE"

echo "Tickety production is verified at https://$PRODUCTION_HOST (build $IMAGE_TAG)"
