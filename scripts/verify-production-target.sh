#!/usr/bin/env bash
set -euo pipefail

PRODUCTION_HOST=tickety.situ.io
PRODUCTION_URL=https://tickety.situ.io
NAMESPACE=""
KUBE_CONTEXT=""
SELF_TEST=false

usage() {
  cat <<'EOF'
Usage: scripts/verify-production-target.sh --namespace NAME [--context NAME]
       scripts/verify-production-target.sh --self-test

Prove that the selected Kubernetes namespace is the Tickety production target.
The gate requires its ingress to own tickety.situ.io, its active frontend build
manifest to match the one served publicly, and the public readiness check to pass.
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
  local match_count

  match_count=$(printf '%s\n' "$ingress_hosts" | awk -v expected="$PRODUCTION_HOST" '$0 == expected { count++ } END { print count + 0 }')
  if [[ $match_count != 1 ]]; then
    echo "Production target rejected: expected exactly one ingress host $PRODUCTION_HOST; found $match_count." >&2
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
    echo "Production target rejected: public frontend manifest does not match the selected workload." >&2
    return 1
  fi
  if ! grep -Eq '"status"[[:space:]]*:[[:space:]]*"ready"' <<<"$readiness_body"; then
    echo "Production target rejected: public readiness response is not ready." >&2
    return 1
  fi
}

self_test() {
  local ready='{"status":"ready"}'

  validate_evidence "$PRODUCTION_HOST" build_123 same_sha same_sha "$ready" >/dev/null
  if validate_evidence tickety.imbell.com build_123 same_sha same_sha "$ready" >/dev/null 2>&1; then
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
  echo "Production target guard self-test passed."
}

while (($#)); do
  case "$1" in
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

if [[ -z $NAMESPACE ]]; then
  echo "--namespace is required." >&2
  usage >&2
  exit 1
fi

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

FRONTEND_POD=$("${KUBECTL[@]}" get pods --namespace "$NAMESPACE" \
  --selector app.kubernetes.io/component=frontend \
  --field-selector status.phase=Running \
  -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
if [[ -z $FRONTEND_POD ]]; then
  FRONTEND_POD=$("${KUBECTL[@]}" get pods --namespace "$NAMESPACE" \
    --selector app=frontend \
    --field-selector status.phase=Running \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
fi
if [[ -z $FRONTEND_POD ]]; then
  echo "Production target rejected: no running frontend Pod in namespace $NAMESPACE." >&2
  exit 1
fi

BUILD_ID=$("${KUBECTL[@]}" exec --namespace "$NAMESPACE" "$FRONTEND_POD" -- cat /app/.next/BUILD_ID)
MANIFEST_PATH="/app/.next/static/$BUILD_ID/_buildManifest.js"
INTERNAL_MANIFEST_SHA=$("${KUBECTL[@]}" exec --namespace "$NAMESPACE" "$FRONTEND_POD" -- cat "$MANIFEST_PATH" | hash_stream)
EXTERNAL_MANIFEST_SHA=$(curl --fail --silent --show-error --max-time 20 \
  "$PRODUCTION_URL/_next/static/$BUILD_ID/_buildManifest.js" | hash_stream)
READINESS_BODY=$(curl --fail --silent --show-error --max-time 20 "$PRODUCTION_URL/api/health/ready")

validate_evidence "$INGRESS_HOSTS" "$BUILD_ID" "$INTERNAL_MANIFEST_SHA" "$EXTERNAL_MANIFEST_SHA" "$READINESS_BODY"

FRONTEND_IMAGE=$("${KUBECTL[@]}" get deployment frontend --namespace "$NAMESPACE" -o jsonpath='{.spec.template.spec.containers[0].image}')
echo "Production target verified: context=$ACTIVE_CONTEXT namespace=$NAMESPACE host=$PRODUCTION_HOST"
echo "Frontend evidence: pod=$FRONTEND_POD image=$FRONTEND_IMAGE build_id=$BUILD_ID manifest_sha256=$INTERNAL_MANIFEST_SHA"
