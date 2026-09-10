#!/usr/bin/env bash
set -euo pipefail

PRODUCTION_HOST=""
PRODUCTION_URL=""
NAMESPACE=""
KUBE_CONTEXT=""
SELF_TEST=false

usage() {
  cat <<'EOF'
Usage: scripts/verify-production-target.sh --host HOST --namespace NAME [--context NAME]
       scripts/verify-production-target.sh --self-test

Prove that the selected Kubernetes namespace is the Tickety production target.
The gate requires its ingress to own the explicit production host, every hashed public asset
from its active frontend build to match the files served publicly, and the public
readiness check to pass.
Run it immediately before and after every production rollout.
EOF
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required command not found: $1" >&2
    exit 1
  fi
}

hash_stream() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum | awk '{print $1}'
  else
    shasum -a 256 | awk '{print $1}'
  fi
}

validate_ingress_host() {
  local ingress_hosts=$1
  local normalized_hosts

  normalized_hosts=$(printf '%s\n' "$ingress_hosts" | sed '/^[[:space:]]*$/d' | LC_ALL=C sort -u)
  if [[ $normalized_hosts != "$PRODUCTION_HOST" ]]; then
    echo "Production target rejected: ingress hosts must be exactly $PRODUCTION_HOST; found: $normalized_hosts." >&2
    return 1
  fi
}

validate_evidence() {
  local ingress_hosts=$1
  local build_id=$2
  local internal_manifest_sha=$3
  local external_manifest_sha=$4
  local readiness_body=$5

  validate_ingress_host "$ingress_hosts" || return 1
  if [[ ! $build_id =~ ^[A-Za-z0-9_-]+$ ]]; then
    echo "Production target rejected: frontend BUILD_ID is missing or malformed." >&2
    return 1
  fi
  if [[ -z $internal_manifest_sha || $internal_manifest_sha != "$external_manifest_sha" ]]; then
    echo "Production target rejected: public frontend asset set does not match the selected workload." >&2
    return 1
  fi
  if ! grep -Eq '"status"[[:space:]]*:[[:space:]]*"ready"' <<<"$readiness_body" || \
     ! grep -Eq '"database"[[:space:]]*:[[:space:]]*"ok"' <<<"$readiness_body"; then
    echo "Production target rejected: public readiness is not ready with database=ok." >&2
    return 1
  fi
}

select_active_frontend_pod() {
  local expected_image=$1

  awk -v expected="$expected_image" \
    '$2 == expected && $3 == "<none>" && $4 == "true" { print $1; exit }'
}

select_single_resource_name() {
  sed '/^[[:space:]]*$/d' | awk 'NR == 1 { selected = $1 } NR > 1 { ambiguous = 1 } END { if (NR == 1 && !ambiguous) print selected; else exit 1 }'
}

self_test() {
  local ready='{"status":"ready","checks":{"database":"ok"}}'
  local pods
  local selected_pod

  PRODUCTION_HOST=prod.tickety.example
  PRODUCTION_URL=https://$PRODUCTION_HOST
  validate_evidence "$PRODUCTION_HOST" build_123 same_sha same_sha "$ready" >/dev/null
  if validate_evidence dev.tickety.example build_123 same_sha same_sha "$ready" >/dev/null 2>&1; then
    echo "Self-test failed: the dev ingress was accepted as production." >&2
    exit 1
  fi
  if validate_evidence "$PRODUCTION_HOST" build_123 internal_sha external_sha "$ready" >/dev/null 2>&1; then
    echo "Self-test failed: a mismatched build manifest was accepted." >&2
    exit 1
  fi
  if validate_evidence "$PRODUCTION_HOST" build_123 same_sha same_sha '{"status":"starting"}' >/dev/null 2>&1; then
    echo "Self-test failed: a non-ready public target was accepted." >&2
    exit 1
  fi
  pods=$'frontend-old old-image 2026-08-23T22:52:09Z true\nfrontend-new current-image <none> true'
  selected_pod=$(select_active_frontend_pod current-image <<<"$pods")
  if [[ $selected_pod != frontend-new ]]; then
    echo "Self-test failed: the active frontend Pod was not selected." >&2
    exit 1
  fi
  if [[ -n $(select_active_frontend_pod old-image <<<"$pods") ]]; then
    echo "Self-test failed: a terminating frontend Pod was selected." >&2
    exit 1
  fi
  if [[ $(select_single_resource_name <<<'deployment.apps/tickety-frontend') != deployment.apps/tickety-frontend ]]; then
    echo "Self-test failed: the labeled frontend Deployment was not selected." >&2
    exit 1
  fi
  if select_single_resource_name <<<$'deployment.apps/frontend-a\ndeployment.apps/frontend-b' >/dev/null 2>&1; then
    echo "Self-test failed: ambiguous frontend Deployments were accepted." >&2
    exit 1
  fi
  if select_single_resource_name </dev/null >/dev/null 2>&1; then
    echo "Self-test failed: a missing frontend Deployment was accepted." >&2
    exit 1
  fi
  echo "Production target guard self-test passed."
}

while (($#)); do
  case "$1" in
    --host)
      PRODUCTION_HOST=${2:?--host requires a value}
      shift 2
      ;;
    --namespace)
      NAMESPACE=${2:?--namespace requires a value}
      shift 2
      ;;
    --context)
      KUBE_CONTEXT=${2:?--context requires a value}
      shift 2
      ;;
    --self-test)
      SELF_TEST=true
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

if [[ $SELF_TEST == true ]]; then
  if [[ -n $NAMESPACE || -n $KUBE_CONTEXT ]]; then
    echo "--self-test does not accept target options." >&2
    exit 1
  fi
  self_test
  exit 0
fi

if [[ -z $NAMESPACE || -z $PRODUCTION_HOST ]]; then
  echo "--host and --namespace are required." >&2
  usage >&2
  exit 1
fi
[[ $PRODUCTION_HOST =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])$ ]] || {
  echo "--host must be a lowercase DNS hostname." >&2
  exit 1
}
PRODUCTION_URL=https://$PRODUCTION_HOST

require_command kubectl
require_command curl
if ! command -v sha256sum >/dev/null 2>&1 && ! command -v shasum >/dev/null 2>&1; then
  echo "Required command not found: sha256sum or shasum" >&2
  exit 1
fi

KUBECTL=(kubectl)
if [[ -n $KUBE_CONTEXT ]]; then
  KUBECTL+=(--context "$KUBE_CONTEXT")
fi

ACTIVE_CONTEXT=$("${KUBECTL[@]}" config current-context)
INGRESS_HOSTS=$("${KUBECTL[@]}" get ingress --namespace "$NAMESPACE" -o jsonpath='{range .items[*].spec.rules[*]}{.host}{"\n"}{end}')
validate_ingress_host "$INGRESS_HOSTS"

FRONTEND_DEPLOYMENTS=$("${KUBECTL[@]}" get deployments --namespace "$NAMESPACE" \
  --selector app.kubernetes.io/component=frontend -o name)
if ! FRONTEND_DEPLOYMENT=$(select_single_resource_name <<<"$FRONTEND_DEPLOYMENTS"); then
  echo "Production target rejected: expected exactly one frontend Deployment selected by app.kubernetes.io/component=frontend in namespace $NAMESPACE." >&2
  exit 1
fi
FRONTEND_IMAGE=$("${KUBECTL[@]}" get "$FRONTEND_DEPLOYMENT" --namespace "$NAMESPACE" -o jsonpath='{.spec.template.spec.containers[0].image}')
FRONTEND_PODS=$("${KUBECTL[@]}" get pods --namespace "$NAMESPACE" \
  --selector app.kubernetes.io/component=frontend \
  --field-selector status.phase=Running \
  -o custom-columns='NAME:.metadata.name,IMAGE:.spec.containers[0].image,DELETING:.metadata.deletionTimestamp,READY:.status.containerStatuses[0].ready' \
  --no-headers 2>/dev/null || true)
FRONTEND_POD=$(select_active_frontend_pod "$FRONTEND_IMAGE" <<<"$FRONTEND_PODS")
if [[ -z $FRONTEND_POD ]]; then
  FRONTEND_PODS=$("${KUBECTL[@]}" get pods --namespace "$NAMESPACE" \
    --selector app=frontend \
    --field-selector status.phase=Running \
    -o custom-columns='NAME:.metadata.name,IMAGE:.spec.containers[0].image,DELETING:.metadata.deletionTimestamp,READY:.status.containerStatuses[0].ready' \
    --no-headers 2>/dev/null || true)
  FRONTEND_POD=$(select_active_frontend_pod "$FRONTEND_IMAGE" <<<"$FRONTEND_PODS")
fi
if [[ -z $FRONTEND_POD ]]; then
  echo "Production target rejected: no ready, non-terminating frontend Pod uses the Deployment image in namespace $NAMESPACE." >&2
  exit 1
fi

BUILD_ID=$("${KUBECTL[@]}" exec --namespace "$NAMESPACE" "$FRONTEND_POD" -- cat /app/.next/BUILD_ID)
MANIFEST_PATH="/app/.next/static/$BUILD_ID/_buildManifest.js"
ASSET_PATHS=$("${KUBECTL[@]}" exec --namespace "$NAMESPACE" "$FRONTEND_POD" -- \
  find /app/.next/static -type f ! -path "$MANIFEST_PATH" ! -path "/app/.next/static/$BUILD_ID/_ssgManifest.js" | LC_ALL=C sort)
INTERNAL_ASSET_MANIFEST=""
EXTERNAL_ASSET_MANIFEST=""
ASSET_COUNT=0
while IFS= read -r ASSET_PATH; do
  [[ -n $ASSET_PATH ]] || continue
  if [[ $ASSET_PATH != /app/.next/static/* || $ASSET_PATH == *"/../"* || $ASSET_PATH == *"/.." ]]; then
    echo "Production target rejected: unsafe frontend asset path: $ASSET_PATH" >&2
    exit 1
  fi
  RELATIVE_PATH=${ASSET_PATH#/app/.next}
  PUBLIC_PATH="/_next$RELATIVE_PATH"
  INTERNAL_ASSET_SHA=$("${KUBECTL[@]}" exec --namespace "$NAMESPACE" "$FRONTEND_POD" -- cat "$ASSET_PATH" | hash_stream)
  EXTERNAL_ASSET_SHA=$(curl --globoff --fail --silent --show-error --max-time 20 "$PRODUCTION_URL$PUBLIC_PATH" | hash_stream)
  INTERNAL_ASSET_MANIFEST+="$PUBLIC_PATH $INTERNAL_ASSET_SHA"$'\n'
  EXTERNAL_ASSET_MANIFEST+="$PUBLIC_PATH $EXTERNAL_ASSET_SHA"$'\n'
  ASSET_COUNT=$((ASSET_COUNT + 1))
done <<<"$ASSET_PATHS"
if ((ASSET_COUNT == 0)); then
  echo "Production target rejected: selected frontend has no public build assets." >&2
  exit 1
fi
INTERNAL_MANIFEST_SHA=$(printf '%s' "$INTERNAL_ASSET_MANIFEST" | hash_stream)
EXTERNAL_MANIFEST_SHA=$(printf '%s' "$EXTERNAL_ASSET_MANIFEST" | hash_stream)
READINESS_BODY=$(curl --fail --silent --show-error --max-time 20 "$PRODUCTION_URL/api/health/ready")

validate_evidence "$INGRESS_HOSTS" "$BUILD_ID" "$INTERNAL_MANIFEST_SHA" "$EXTERNAL_MANIFEST_SHA" "$READINESS_BODY"

echo "Production target verified: context=$ACTIVE_CONTEXT namespace=$NAMESPACE host=$PRODUCTION_HOST"
echo "Frontend evidence: pod=$FRONTEND_POD image=$FRONTEND_IMAGE build_id=$BUILD_ID assets=$ASSET_COUNT asset_set_sha256=$INTERNAL_MANIFEST_SHA"
