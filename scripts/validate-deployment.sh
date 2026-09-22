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
"$ROOT_DIR/deploy.sh" --self-test
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
grep -Fq 'tickety.example.com' "$ROOT_DIR/deploy/examples/production-values.yaml"
grep -Fq -- '--metadata-file' "$ROOT_DIR/deploy.sh"
grep -Fq -- 'docker buildx imagetools inspect' "$ROOT_DIR/deploy.sh"
grep -Fq -- 'BUNDLED_POSTGRESQL_IMAGE=$(rendered_bundled_postgresql_image)' "$ROOT_DIR/deploy.sh"
grep -Fq -- 'ensure_namespace_for_external_secret' "$ROOT_DIR/deploy.sh"
grep -Fq -- 'imageDigestPolicy.requireDigests=true' "$ROOT_DIR/deploy.sh"
grep -Fq -- 'existingSecretRolloutToken=$EXTERNAL_SECRET_RESOURCE_VERSION' "$ROOT_DIR/deploy.sh"
grep -Fq -- 'changed from resourceVersion' "$ROOT_DIR/deploy.sh"
grep -Fq 'production appMode or deploymentClass requires imageDigestPolicy.requireDigests=true' \
  "$CHART_DIR/templates/configmap.yaml"
grep -Fq 'production existingSecret requires an immutable existingSecretRolloutToken' \
  "$CHART_DIR/templates/configmap.yaml"
grep -Fq 'define "tickety.postgresqlImage"' "$CHART_DIR/templates/_helpers.tpl"
grep -Fq 'tickety.io/bundled-postgresql-image' "$CHART_DIR/templates/configmap.yaml"
grep -Fq 'requireDigests: true' "$ROOT_DIR/deploy/examples/production-values.yaml"
[[ $(grep -Ec '^[[:space:]]*digest:[[:space:]]*sha256:[a-f0-9]{64}[[:space:]]*$' \
  "$ROOT_DIR/deploy/examples/production-values.yaml") -eq 3 ]] || {
  echo "Production values must provide backend, frontend, and bundled PostgreSQL sha256 manifest digests." >&2
  exit 1
}
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
  # Rendering never needs a real credential. Supplying an external-Secret name
  # exercises the production ownership path without weakening the chart's
  # chart-managed-Secret keyring gate or placing test key material in output.
  validation_existing_secret=tickety-validation-runtime-secrets
  echo "Linting Helm chart..."
  helm lint --strict --kube-version 1.25.0 "$CHART_DIR" \
    --set-string existingSecret="$validation_existing_secret"
  temporary_dir=$(mktemp -d)
  cleanup() { rm -rf -- "$temporary_dir"; }
  trap cleanup EXIT
  helm template tickety "$CHART_DIR" --namespace tickety --kube-version 1.25.0 \
    --values "$ROOT_DIR/deploy/examples/production-values.yaml" \
    --set-string existingSecret="$validation_existing_secret" \
    --set-string existingSecretRolloutToken=validation-resource-version >"$temporary_dir/production.yaml"
  helm template tickety "$CHART_DIR" --namespace tickety --kube-version 1.25.0 \
    --set ingress.enabled=true --set ingress.host=tickety.example.test \
    --set-string existingSecret="$validation_existing_secret" >"$temporary_dir/ingress.yaml"
  helm template tickety "$CHART_DIR" --namespace tickety --kube-version 1.25.0 \
    --set backup.enabled=true \
    --set-string existingSecret="$validation_existing_secret" >"$temporary_dir/backup.yaml"
  if helm template tickety "$CHART_DIR" --namespace tickety --kube-version 1.25.0 \
    --set-string existingSecret="$validation_existing_secret" \
    --set-string worker.image.tag=validation-image-drift >/dev/null 2>&1; then
    echo "Helm chart accepted a worker image that differs from backend/migration." >&2
    exit 1
  fi
  if helm template tickety "$CHART_DIR" --namespace tickety --kube-version 1.25.0 \
    --values "$ROOT_DIR/deploy/examples/production-values.yaml" \
    --set-string existingSecret="$validation_existing_secret" >/dev/null 2>&1; then
    echo "Production Helm chart accepted an external Secret without a rollout resourceVersion token." >&2
    exit 1
  fi
  if helm template tickety "$CHART_DIR" --namespace tickety --kube-version 1.25.0 \
    --set-string existingSecret="$validation_existing_secret" \
    --set imageDigestPolicy.requireDigests=true >/dev/null 2>&1; then
    echo "Helm chart accepted tag-only application images while digest policy is enabled." >&2
    exit 1
  fi
  if helm template tickety "$CHART_DIR" --namespace tickety --kube-version 1.25.0 \
    --set config.appMode=production --set config.deploymentClass=poc \
    --set-string existingSecret="$validation_existing_secret" >/dev/null 2>&1; then
    echo "Helm chart accepted production appMode while digest policy was disabled." >&2
    exit 1
  fi
  if helm template tickety "$CHART_DIR" --namespace tickety --kube-version 1.25.0 \
    --set imageDigestPolicy.requireDigests=true \
    --set-string existingSecret="$validation_existing_secret" \
    --set-string backend.image.digest=sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef \
    --set-string frontend.image.digest=sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef >/dev/null 2>&1; then
    echo "Helm chart accepted a bundled PostgreSQL tag while digest policy was enabled." >&2
    exit 1
  fi
  if helm template tickety "$CHART_DIR" --namespace tickety --kube-version 1.25.0 \
    --set-string existingSecret="$validation_existing_secret" \
    --set-string worker.image.digest=sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef >/dev/null 2>&1; then
    echo "Helm chart accepted a worker digest that differs from backend/migration." >&2
    exit 1
  fi
  if helm template tickety "$CHART_DIR" --namespace tickety --kube-version 1.25.0 \
    --set-string existingSecret="$validation_existing_secret" \
    --set-string config.extra.AZURE_STORAGE_CONNECTION_STRING=validation-only >/dev/null 2>&1; then
    echo "Helm chart accepted a credential-like config.extra key." >&2
    exit 1
  fi
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
    if Path(filename).name == "backup.yaml":
        claims = [
            document for document in documents
            if document.get("kind") == "PersistentVolumeClaim"
            and document.get("metadata", {}).get("labels", {}).get(
                "app.kubernetes.io/component"
            ) == "backup"
        ]
        if len(claims) != 1:
            raise SystemExit(f"{filename}: expected one chart-managed backup PVC")
        if claims[0].get("metadata", {}).get("annotations", {}).get(
            "helm.sh/resource-policy"
        ) != "keep":
            raise SystemExit(f"{filename}: chart-managed backup PVC is not retained")
    if Path(filename).name != "production.yaml":
        continue

    def container_image(component, kind, container):
        matches = [
            document for document in documents
            if document.get("kind") == kind
            and document.get("metadata", {}).get("labels", {}).get(
                "app.kubernetes.io/component"
            ) == component
        ]
        if len(matches) != 1:
            raise SystemExit(f"{filename}: expected one {component} {kind}")
        pod_spec = matches[0]["spec"]["template"]["spec"]
        containers = [
            item for item in pod_spec.get("containers", [])
            if item.get("name") == container
        ]
        if len(containers) != 1 or not containers[0].get("image"):
            raise SystemExit(f"{filename}: missing {component} image")
        return containers[0]["image"]

    backend_release_images = {
        container_image("backend", "Deployment", "backend"),
        container_image("worker", "Deployment", "worker"),
        container_image("migration", "Job", "migrate"),
    }
    if len(backend_release_images) != 1:
        raise SystemExit(f"{filename}: backend, worker, and migration images drift")
    release_images = backend_release_images | {
        container_image("frontend", "Deployment", "frontend"),
    }
    if not all("@sha256:" in image and image.count("@") == 1 for image in release_images):
        raise SystemExit(f"{filename}: production application images are not digest-pinned")
    configmaps = [
        document for document in documents
        if document.get("kind") == "ConfigMap"
        and document.get("metadata", {}).get("name", "").endswith("-config")
    ]
    if len(configmaps) != 1:
        raise SystemExit(f"{filename}: expected one runtime ConfigMap")
    if any(key.startswith("TICKETY_SETTINGS_ENCRYPTION_") for key in configmaps[0].get("data", {})):
        raise SystemExit(f"{filename}: settings-encryption material reached a ConfigMap")
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
