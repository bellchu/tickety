#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CHART_DIR="$ROOT_DIR/deploy/helm/tickety"

usage() {
  cat <<'EOF'
Usage:
  ./deploy.sh docker
  ./deploy.sh kubernetes --registry REGISTRY_PREFIX [options]
  ./deploy.sh --self-test

Docker options:
  No flags are required. Configure optional settings in .env.

Kubernetes options:
  --registry PREFIX   Registry path, for example registry.example.com/tickety
  --tag TAG           Build tag used while pushing (default: Git SHA plus timestamp)
  --backend-digest DIGEST
                      Existing backend manifest digest for --skip-build (sha256:...)
  --frontend-digest DIGEST
                      Existing frontend manifest digest for --skip-build (sha256:...)
  --postgresql-digest DIGEST
                      Bundled PostgreSQL manifest digest when postgresql.enabled=true
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

helm_supports_reset_then_reuse_values() {
  [[ ${1:-} == *"--reset-then-reuse-values"* ]]
}

require_safe_helm_upgrade_values_strategy() {
  local upgrade_help
  if ! upgrade_help=$(helm upgrade --help); then
    echo "Unable to inspect Helm upgrade capabilities." >&2
    exit 1
  fi
  if ! helm_supports_reset_then_reuse_values "$upgrade_help"; then
    echo "Helm 3.14+ or Helm 4 is required: safe upgrades need --reset-then-reuse-values." >&2
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

is_oci_manifest_digest() {
  [[ ${1:-} =~ ^sha256:[a-f0-9]{64}$ ]]
}

require_oci_manifest_digest() {
  local digest=$1
  local label=$2
  if ! is_oci_manifest_digest "$digest"; then
    echo "$label must be a sha256 OCI manifest digest (sha256: plus 64 lowercase hexadecimal characters)." >&2
    exit 1
  fi
}

buildx_metadata_digest() {
  local metadata_file=$1
  local digest

  # Buildx records the pushed OCI manifest/index digest in its metadata file.
  # The tag is a build transport only; the release below uses this digest.
  digest=$(sed -nE 's/.*"containerimage.digest"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p' "$metadata_file")
  if [[ $digest == *$'\n'* || -z $digest ]] || ! is_oci_manifest_digest "$digest"; then
    echo "Buildx did not return one valid pushed OCI manifest digest in $metadata_file." >&2
    exit 1
  fi
  printf '%s' "$digest"
}

verify_registry_manifest() {
  local repository=$1
  local digest=$2

  # Verify that the exact reference is readable from the configured registry
  # before an upgrade drains current database writers. This also gives the
  # release log an auditable registry-resolution gate for --skip-build.
  if ! docker buildx imagetools inspect "$repository@$digest" >/dev/null; then
    echo "Registry does not expose the required immutable image: $repository@$digest" >&2
    exit 1
  fi
}

external_secret_name_from_rendered_configmap() {
  local rendered=$1
  local names

  names=$(printf '%s\n' "$rendered" | sed -nE 's/^[[:space:]]*tickety\.io\/existing-secret-name:[[:space:]]*"?([^"[:space:]]+)"?[[:space:]]*$/\1/p')
  if [[ $names == *$'\n'* ]]; then
    echo "Rendered chart has multiple external Secret identities; refusing deployment." >&2
    return 1
  fi
  if [[ -n $names ]]; then
    validate_kubernetes_name "$names" "Rendered existing Secret" 253
  fi
  printf '%s' "$names"
}

rendered_existing_secret_name() {
  local rendered

  # Render only the ConfigMap with a harmless probe token. The annotation is
  # chart-owned metadata, never Secret data, and is the authoritative result of
  # values-file layering rather than an ad-hoc YAML parser in this script.
  rendered=$(helm template "$RELEASE" "$CHART_DIR" --namespace "$NAMESPACE" \
    --show-only templates/configmap.yaml --kube-version 1.25.0 \
    "${HELM_VALUE_ARGS[@]}" --set-string existingSecretRolloutToken=probe)
  external_secret_name_from_rendered_configmap "$rendered"
}

bundled_postgresql_image_from_rendered_configmap() {
  local rendered=$1
  local images

  images=$(printf '%s\n' "$rendered" | sed -nE 's/^[[:space:]]*tickety\.io\/bundled-postgresql-image:[[:space:]]*"?([^"[:space:]]+)"?[[:space:]]*$/\1/p')
  if [[ $images == *$'\n'* ]]; then
    echo "Rendered chart has multiple bundled PostgreSQL image identities; refusing deployment." >&2
    return 1
  fi
  if [[ -n $images && ! $images =~ ^.+@sha256:[a-f0-9]{64}$ ]]; then
    echo "Rendered bundled PostgreSQL image is not an immutable sha256 reference; refusing deployment." >&2
    return 1
  fi
  printf '%s' "$images"
}

rendered_bundled_postgresql_image() {
  local rendered

  rendered=$(helm template "$RELEASE" "$CHART_DIR" --namespace "$NAMESPACE" \
    --show-only templates/configmap.yaml --kube-version 1.25.0 \
    "${HELM_VALUE_ARGS[@]}" --set-string existingSecretRolloutToken=probe)
  bundled_postgresql_image_from_rendered_configmap "$rendered"
}

namespace_needs_creation() {
  [[ -z ${1:-} ]]
}

ensure_namespace_for_external_secret() {
  local namespace_name

  if ! namespace_name=$(kubectl get namespace "$NAMESPACE" --ignore-not-found --output=name); then
    echo "Unable to inspect Kubernetes namespace $NAMESPACE before binding an external Secret." >&2
    exit 1
  fi
  if ! namespace_needs_creation "$namespace_name"; then
    return 0
  fi
  echo "Creating Kubernetes namespace $NAMESPACE before binding the external Secret..."
  kubectl create namespace "$NAMESPACE"
  if ! namespace_name=$(kubectl get namespace "$NAMESPACE" --output=name) || [[ -z $namespace_name ]]; then
    echo "Kubernetes namespace $NAMESPACE was not readable after creation; refusing deployment." >&2
    exit 1
  fi
}

secret_resource_version() {
  local secret_name=$1
  local resource_version

  if ! resource_version=$(kubectl get secret --namespace "$NAMESPACE" "$secret_name" \
    --output=jsonpath='{.metadata.resourceVersion}'); then
    echo "Unable to read resourceVersion for external Secret $secret_name; refusing deployment." >&2
    exit 1
  fi
  if [[ -z $resource_version || $resource_version =~ [[:space:]] ]]; then
    echo "External Secret $secret_name has no usable resourceVersion; refusing deployment." >&2
    exit 1
  fi
  printf '%s' "$resource_version"
}

release_operation_from_status() {
  local release_status=$1

  # `helm status` also succeeds for a retained, historically uninstalled
  # release. It has no live workload, so it must use install semantics rather
  # than an ordinary upgrade.
  if [[ $release_status =~ \"status\"[[:space:]]*:[[:space:]]*\"uninstalled\" ]]; then
    printf 'install'
    return 0
  fi
  # A failed release is upgradeable with a forward-compatible recovery. Other
  # transitional/unknown states fail closed rather than treating an in-progress
  # operation as an ordinary upgrade.
  if [[ $release_status =~ \"status\"[[:space:]]*:[[:space:]]*\"(deployed|failed)\" ]]; then
    printf 'upgrade'
    return 0
  fi
  return 1
}

drain_database_writers_for_auth_schema_cutover() {
  local backend_selector="app.kubernetes.io/instance=$RELEASE,app.kubernetes.io/component=backend"
  local worker_selector="app.kubernetes.io/instance=$RELEASE,app.kubernetes.io/component=worker"
  local backend_deployment
  local worker_deployment
  local remaining_pods
  local pod
  local component
  local component_selector

  # The migration Job and a Helm rolling update otherwise overlap. An old API
  # Pod or a scheduled worker could write or consume state after the schema
  # cutover but before it understands the new revocation boundary. Require
  # exactly one live backend Deployment. A worker is optional in the chart,
  # but when present it is also a database writer and must be drained.
  if ! backend_deployment=$(kubectl get deployment --namespace "$NAMESPACE" \
    --selector="$backend_selector" --output=name); then
    echo "Unable to identify the current backend Deployment for auth schema cutover." >&2
    exit 1
  fi
  if [[ -z $backend_deployment || $backend_deployment == *$'\n'* ]]; then
    echo "Expected exactly one backend Deployment for release $RELEASE in namespace $NAMESPACE; refusing mixed-version authentication rollout." >&2
    exit 1
  fi
  if ! worker_deployment=$(kubectl get deployment --namespace "$NAMESPACE" \
    --selector="$worker_selector" --output=name); then
    echo "Unable to identify the current worker Deployment for auth schema cutover." >&2
    exit 1
  fi
  if [[ $worker_deployment == *$'\n'* ]]; then
    echo "Expected at most one worker Deployment for release $RELEASE in namespace $NAMESPACE; refusing mixed-version authentication rollout." >&2
    exit 1
  fi

  echo "Draining current backend API and worker Pods before the authentication schema cutover; API service and scheduled work will be briefly unavailable..."
  kubectl scale --namespace "$NAMESPACE" "$backend_deployment" --replicas=0
  if [[ -n $worker_deployment ]]; then
    kubectl scale --namespace "$NAMESPACE" "$worker_deployment" --replicas=0
  fi
  kubectl rollout status --namespace "$NAMESPACE" "$backend_deployment" --timeout="$HELM_TIMEOUT"
  if [[ -n $worker_deployment ]]; then
    kubectl rollout status --namespace "$NAMESPACE" "$worker_deployment" --timeout="$HELM_TIMEOUT"
  fi

  # Bash 3.2 has no mapfile. Re-list until no matching Pod remains so a
  # terminating old API or worker cannot overlap the migration Job or new
  # rollout. The worker selector is checked even when its Deployment was
  # absent, closing the stale-Pod path after a worker was disabled.
  for component in backend worker; do
    if [[ $component == backend ]]; then
      component_selector=$backend_selector
    else
      component_selector=$worker_selector
    fi
    while :; do
      if ! remaining_pods=$(kubectl get pods --namespace "$NAMESPACE" \
        --selector="$component_selector" --output=name); then
        echo "Unable to confirm $component Pods have exited before auth schema cutover." >&2
        exit 1
      fi
      [[ -z $remaining_pods ]] && break
      while IFS= read -r pod; do
        [[ -z $pod ]] && continue
        kubectl wait --namespace "$NAMESPACE" --for=delete "$pod" --timeout="$HELM_TIMEOUT"
      done <<< "$remaining_pods"
    done
  done
}

run_self_test() {
  [[ $(release_operation_from_status '{"info":{"status":"uninstalled"}}') == install ]] || return 1
  [[ $(release_operation_from_status '{"info":{"status":"deployed"}}') == upgrade ]] || return 1
  [[ $(release_operation_from_status '{"info":{"status":"failed"}}') == upgrade ]] || return 1
  if release_operation_from_status '{"info":{"status":"pending-upgrade"}}' >/dev/null; then
    return 1
  fi
  helm_supports_reset_then_reuse_values '--reset-then-reuse-values' || return 1
  if helm_supports_reset_then_reuse_values '--reuse-values'; then
    return 1
  fi
  is_oci_manifest_digest "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef" || return 1
  if is_oci_manifest_digest 'sha256:UPPERCASE'; then
    return 1
  fi
  [[ $(buildx_metadata_digest <(printf '%s\n' '{"containerimage.digest":"sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"}')) == sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef ]] || return 1
  [[ $(external_secret_name_from_rendered_configmap $'metadata:\n  annotations:\n    tickety.io/existing-secret-name: "tickety-runtime-secrets"') == tickety-runtime-secrets ]] || return 1
  [[ $(bundled_postgresql_image_from_rendered_configmap $'metadata:\n  annotations:\n    tickety.io/bundled-postgresql-image: "registry.example.test/pgvector@sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"') == registry.example.test/pgvector@sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef ]] || return 1
  namespace_needs_creation '' || return 1
  if namespace_needs_creation namespace/tickety; then
    return 1
  fi
  echo "Deployment release-state self-test passed."
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
if [[ $MODE == --self-test ]]; then
  run_self_test
  exit 0
fi
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
BACKEND_DIGEST=""
FRONTEND_DIGEST=""
POSTGRESQL_DIGEST=""
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
    --backend-digest)
      BACKEND_DIGEST=${2:?--backend-digest requires a value}
      shift 2
      ;;
    --frontend-digest)
      FRONTEND_DIGEST=${2:?--frontend-digest requires a value}
      shift 2
      ;;
    --postgresql-digest)
      POSTGRESQL_DIGEST=${2:?--postgresql-digest requires a value}
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
if [[ $SKIP_BUILD == true && $TAG_WAS_PROVIDED == true ]]; then
  echo "--tag is a build transport tag and is not accepted with --skip-build; deploy the explicit digests instead." >&2
  exit 1
fi
if [[ -z $IMAGE_TAG ]]; then
  if [[ $SKIP_BUILD == true ]]; then
    # Helm's generic image schema retains a tag field for local evaluation,
    # but digest-pinned references ignore it. Do not fabricate a timestamp/Git
    # tag that could be mistaken for the identity of a skipped build.
    IMAGE_TAG=digest-pinned
  else
    IMAGE_TAG="${BUILD_SHA}-$(date -u +%Y%m%d%H%M%S)"
  fi
fi
if [[ ! $IMAGE_TAG =~ ^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$ ]]; then
  echo "Invalid container image tag: $IMAGE_TAG" >&2
  exit 1
fi
if [[ $IMAGE_TAG =~ ^[lL][aA][tT][eE][sS][tT]$ ]]; then
  echo "Kubernetes production builds must use a build-specific transport tag, not latest." >&2
  exit 1
fi
if [[ $SKIP_BUILD == true ]]; then
  if [[ -z $BACKEND_DIGEST || -z $FRONTEND_DIGEST ]]; then
    echo "--skip-build requires both --backend-digest and --frontend-digest; tags are not production image identities." >&2
    exit 1
  fi
  require_oci_manifest_digest "$BACKEND_DIGEST" "--backend-digest"
  require_oci_manifest_digest "$FRONTEND_DIGEST" "--frontend-digest"
elif [[ -n $BACKEND_DIGEST || -n $FRONTEND_DIGEST ]]; then
  echo "--backend-digest and --frontend-digest are only accepted with --skip-build; built releases use Buildx's pushed digest metadata." >&2
  exit 1
fi
if [[ -n $POSTGRESQL_DIGEST ]]; then
  require_oci_manifest_digest "$POSTGRESQL_DIGEST" "--postgresql-digest"
fi

require_command kubectl
require_command helm
require_safe_helm_upgrade_values_strategy
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

if [[ $SKIP_BUILD == false ]]; then
  require_command docker
  if ! docker buildx version >/dev/null 2>&1; then
    echo "Docker Buildx is required to build portable Kubernetes images." >&2
    exit 1
  fi
  IMAGE_METADATA_DIR=$(mktemp -d)
  cleanup_image_metadata() { rm -rf -- "$IMAGE_METADATA_DIR"; }
  trap cleanup_image_metadata EXIT
  echo "Building and pushing OCI production images..."
  docker buildx build --platform "$PLATFORM" --target backend --push \
    --tag "$BACKEND_REPOSITORY:$IMAGE_TAG" \
    --metadata-file "$IMAGE_METADATA_DIR/backend.json" \
    --build-arg "BUILD_SHA=$BUILD_SHA" --build-arg "BUILD_TIME=$BUILD_TIME" \
    "$ROOT_DIR"
  BACKEND_DIGEST=$(buildx_metadata_digest "$IMAGE_METADATA_DIR/backend.json")
  docker buildx build --platform "$PLATFORM" --target frontend --push \
    --tag "$FRONTEND_REPOSITORY:$IMAGE_TAG" \
    --metadata-file "$IMAGE_METADATA_DIR/frontend.json" \
    --build-arg "BUILD_SHA=$BUILD_SHA" --build-arg "BUILD_TIME=$BUILD_TIME" \
    "$ROOT_DIR"
  FRONTEND_DIGEST=$(buildx_metadata_digest "$IMAGE_METADATA_DIR/frontend.json")
fi

# Values must be rendered only after a build has produced its registry digest.
# Every application workload then receives repository@digest, never a mutable
# registry tag. The tag remains in Helm values as an audit breadcrumb only.
HELM_VALUE_ARGS=()
if [[ -n $VALUES_FILE ]]; then
  HELM_VALUE_ARGS+=(--values "$VALUES_FILE")
fi
HELM_VALUE_ARGS+=(
  --set-string "config.frontendUrl=https://$PRODUCTION_HOST"
  --set-string "config.corsAllowOrigins=https://$PRODUCTION_HOST"
  --set-string "config.appMode=production"
  --set-string "config.deploymentClass=production"
  --set-string "ingress.host=$PRODUCTION_HOST"
  --set-string "backend.image.repository=$BACKEND_REPOSITORY"
  --set-string "backend.image.tag=$IMAGE_TAG"
  --set-string "backend.image.digest=$BACKEND_DIGEST"
  --set-string "frontend.image.repository=$FRONTEND_REPOSITORY"
  --set-string "frontend.image.tag=$IMAGE_TAG"
  --set-string "frontend.image.digest=$FRONTEND_DIGEST"
  --set imageDigestPolicy.requireDigests=true
)
if [[ -n $POSTGRESQL_DIGEST ]]; then
  # Leave a values-file digest intact when the CLI option is omitted. The chart
  # itself fails closed if its bundled database is enabled without either one.
  HELM_VALUE_ARGS+=(--set-string "postgresql.image.digest=$POSTGRESQL_DIGEST")
fi

# Resolve every final, chart-rendered production image before Helm can drain an
# existing release. This includes the bundled PostgreSQL StatefulSet and backup
# CronJob when enabled, while an external database emits no such image.
BUNDLED_POSTGRESQL_IMAGE=$(rendered_bundled_postgresql_image)
require_command docker
if ! docker buildx version >/dev/null 2>&1; then
  echo "Docker Buildx is required to verify immutable Kubernetes image references." >&2
  exit 1
fi
verify_registry_manifest "$BACKEND_REPOSITORY" "$BACKEND_DIGEST"
verify_registry_manifest "$FRONTEND_REPOSITORY" "$FRONTEND_DIGEST"
if [[ -n $BUNDLED_POSTGRESQL_IMAGE ]]; then
  verify_registry_manifest "${BUNDLED_POSTGRESQL_IMAGE%@*}" "${BUNDLED_POSTGRESQL_IMAGE#*@}"
fi

EXTERNAL_SECRET_NAME=$(rendered_existing_secret_name)
EXTERNAL_SECRET_RESOURCE_VERSION=""
if [[ -n $EXTERNAL_SECRET_NAME ]]; then
  ensure_namespace_for_external_secret
  EXTERNAL_SECRET_RESOURCE_VERSION=$(secret_resource_version "$EXTERNAL_SECRET_NAME")
  HELM_VALUE_ARGS+=(--set-string "existingSecretRolloutToken=$EXTERNAL_SECRET_RESOURCE_VERSION")
  echo "Bound external Secret $EXTERNAL_SECRET_NAME to resourceVersion $EXTERNAL_SECRET_RESOURCE_VERSION for this release."
fi

echo "Validating Helm configuration with immutable registry digests..."
helm lint --strict --kube-version 1.25.0 "$CHART_DIR" "${HELM_VALUE_ARGS[@]}"
helm template "$RELEASE" "$CHART_DIR" --namespace "$NAMESPACE" \
  --kube-version 1.25.0 "${HELM_VALUE_ARGS[@]}" >/dev/null

if release_status=$(helm status "$RELEASE" --namespace "$NAMESPACE" --output json 2>&1); then
  if ! RELEASE_OPERATION=$(release_operation_from_status "$release_status"); then
    echo "Helm release $RELEASE is not in an upgradeable state:" >&2
    echo "$release_status" >&2
    exit 1
  fi
elif [[ $release_status == *"release: not found"* ]]; then
  RELEASE_OPERATION=install
else
  echo "Unable to determine whether Helm release $RELEASE already exists:" >&2
  echo "$release_status" >&2
  exit 1
fi

if [[ $RELEASE_OPERATION == upgrade ]]; then
  # Authentication epoch migration 0056 deliberately revokes existing browser
  # sessions and in-flight SSO states. Drain every old database writer first:
  # old binaries cannot safely coexist with that cutover even for a rolling-
  # update window.
  drain_database_writers_for_auth_schema_cutover
  # Database migrations are forward-only and production verifies the exact
  # Alembic head. If this migration Job advances the schema, rolling Kubernetes
  # objects back to the prior image cannot restore a compatible application.
  # Retain the failed revision so recovery is an explicit forward fix or a
  # backup restore, never a misleading automatic old-image rollback.
  HELM_ARGS=(
    upgrade "$RELEASE" "$CHART_DIR"
    --namespace "$NAMESPACE"
    # Keep release-specific production configuration (including external
    # database/Secret ownership) while layering new chart defaults and this
    # deployment's explicit image/origin overrides. Bare upgrades with --set
    # reset prior values and can silently point the migration Job at another DB.
    --reset-then-reuse-values
    "${HELM_VALUE_ARGS[@]}"
    --wait
    --wait-for-jobs
    --timeout "$HELM_TIMEOUT"
  )
  echo "Upgrading Helm release $RELEASE in OCI Kubernetes namespace $NAMESPACE; failed revisions are retained for forward recovery..."
else
  # Do not use --atomic for a first install: a failed install must retain its
  # StatefulSet PVC and diagnostic resources for a safe retry.
  HELM_ARGS=(
    upgrade --install "$RELEASE" "$CHART_DIR"
    --namespace "$NAMESPACE"
    --create-namespace
    "${HELM_VALUE_ARGS[@]}"
    --wait
    --wait-for-jobs
    --timeout "$HELM_TIMEOUT"
  )
  echo "Installing Helm release $RELEASE in OCI Kubernetes namespace $NAMESPACE..."
fi

helm "${HELM_ARGS[@]}"
helm test "$RELEASE" --namespace "$NAMESPACE" --timeout 2m
"$ROOT_DIR/scripts/verify-production-target.sh" --host "$PRODUCTION_HOST" --namespace "$NAMESPACE" --release "$RELEASE"
if [[ -n $EXTERNAL_SECRET_NAME ]]; then
  CURRENT_SECRET_RESOURCE_VERSION=$(secret_resource_version "$EXTERNAL_SECRET_NAME")
  if [[ $CURRENT_SECRET_RESOURCE_VERSION != "$EXTERNAL_SECRET_RESOURCE_VERSION" ]]; then
    echo "External Secret $EXTERNAL_SECRET_NAME changed from resourceVersion $EXTERNAL_SECRET_RESOURCE_VERSION to $CURRENT_SECRET_RESOURCE_VERSION during deployment; release is intentionally not accepted." >&2
    exit 1
  fi
fi

echo "Tickety production is verified at https://$PRODUCTION_HOST (backend $BACKEND_REPOSITORY@$BACKEND_DIGEST; frontend $FRONTEND_REPOSITORY@$FRONTEND_DIGEST)"
