#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CHART_DIR="$ROOT_DIR/deploy/helm/tickety"

usage() {
  cat <<'EOF'
Usage:
  ./deploy.sh docker
  ./deploy.sh kubernetes --registry REGISTRY_PREFIX [options]
  ./deploy.sh aks --acr ACR_NAME [options]

Docker options:
  No flags are required. Configure optional settings in .env.

Kubernetes and AKS options:
  --registry PREFIX   Registry path, for example ghcr.io/acme/tickety
  --acr NAME          Azure Container Registry name (AKS mode only)
  --tag TAG           Immutable image tag (default: Git SHA plus timestamp)
  --namespace NAME    Kubernetes namespace (default: tickety)
  --release NAME      Helm release name (default: tickety)
  --values FILE       Additional Helm values file
  --platform VALUE    Buildx target platform (default: linux/amd64)
  --timeout VALUE     Helm timeout (default: 10m)
  --skip-build        Deploy images that already exist in the registry

Examples:
  ./deploy.sh docker
  ./deploy.sh kubernetes --registry ghcr.io/acme/tickety --values tickety-values.yaml
  ./deploy.sh aks --acr myregistry --values tickety-values.yaml
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

  docker compose -f "$ROOT_DIR/docker-compose.yml" config --quiet
  docker compose -f "$ROOT_DIR/docker-compose.yml" up --detach --build --wait
  FRONTEND_BINDING=$(docker compose -f "$ROOT_DIR/docker-compose.yml" port frontend 3000)
  echo "Tickety is ready on $FRONTEND_BINDING"
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

if [[ $MODE != kubernetes && $MODE != aks ]]; then
  echo "Unknown deployment mode: $MODE" >&2
  usage >&2
  exit 1
fi

REGISTRY_PREFIX=""
ACR_NAME=""
IMAGE_TAG=""
TAG_WAS_PROVIDED=false
NAMESPACE=tickety
RELEASE=tickety
VALUES_FILE=""
PLATFORM=linux/amd64
HELM_TIMEOUT=10m
SKIP_BUILD=false

while (($#)); do
  case "$1" in
    --registry)
      REGISTRY_PREFIX=${2:?--registry requires a value}
      shift 2
      ;;
    --acr)
      ACR_NAME=${2:?--acr requires a value}
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

if [[ $MODE == aks ]]; then
  if [[ -z $ACR_NAME ]]; then
    echo "AKS mode requires --acr ACR_NAME." >&2
    exit 1
  fi
elif [[ -z $REGISTRY_PREFIX ]]; then
  echo "Kubernetes mode requires --registry REGISTRY_PREFIX." >&2
  exit 1
fi

require_command kubectl
require_command helm
KUBE_CONTEXT=$(kubectl config current-context)
kubectl cluster-info >/dev/null
echo "Kubernetes context: $KUBE_CONTEXT"

if [[ $MODE == aks ]]; then
  require_command az
  REGISTRY_SERVER=$(az acr show --name "$ACR_NAME" --query loginServer --output tsv)
  if [[ -z $REGISTRY_SERVER ]]; then
    echo "Could not resolve the login server for ACR: $ACR_NAME" >&2
    exit 1
  fi
  REGISTRY_PREFIX="${REGISTRY_SERVER%/}/tickety"
fi

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
  --set-string "backend.image.repository=$BACKEND_REPOSITORY"
  --set-string "backend.image.tag=$IMAGE_TAG"
  --set-string "frontend.image.repository=$FRONTEND_REPOSITORY"
  --set-string "frontend.image.tag=$IMAGE_TAG"
)

echo "Validating Helm configuration..."
helm lint "$CHART_DIR" "${HELM_VALUE_ARGS[@]}"
helm template "$RELEASE" "$CHART_DIR" --namespace "$NAMESPACE" \
  "${HELM_VALUE_ARGS[@]}" >/dev/null

if [[ $SKIP_BUILD == false && $MODE == aks ]]; then
  echo "Building backend and frontend images in Azure Container Registry..."
  az acr build --registry "$ACR_NAME" --target backend \
    --image "tickety/backend:$IMAGE_TAG" \
    --build-arg "BUILD_SHA=$BUILD_SHA" --build-arg "BUILD_TIME=$BUILD_TIME" \
    "$ROOT_DIR"
  az acr build --registry "$ACR_NAME" --target frontend \
    --image "tickety/frontend:$IMAGE_TAG" \
    --build-arg "BUILD_SHA=$BUILD_SHA" --build-arg "BUILD_TIME=$BUILD_TIME" \
    "$ROOT_DIR"
elif [[ $SKIP_BUILD == false ]]; then
  require_command docker
  if ! docker buildx version >/dev/null 2>&1; then
    echo "Docker Buildx is required to build portable Kubernetes images." >&2
    exit 1
  fi
  echo "Building and pushing backend and frontend images..."
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
  --atomic
  --timeout "$HELM_TIMEOUT"
)

echo "Deploying Helm release $RELEASE to namespace $NAMESPACE..."
helm "${HELM_ARGS[@]}"
helm test "$RELEASE" --namespace "$NAMESPACE" --timeout 2m

echo "Deployment complete."
kubectl get pods,jobs,service,ingress --namespace "$NAMESPACE"
