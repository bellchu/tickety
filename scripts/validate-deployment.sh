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

Validate the Docker Compose configuration, Helm chart, and Kubernetes manifests
using every available local tool. By default, unavailable optional tools are
reported and skipped. Require a tool explicitly for CI or a strict local check.

Options:
  --require-docker   Fail unless Docker Compose v2 is available.
  --require-helm     Fail unless Helm is available.
  --require-kubectl  Fail unless kubectl is available.
  --require-kubectl-cluster
                    Fail unless kubectl can reach a Kubernetes API server.
  --require-yaml     Fail unless Python with PyYAML is available.
  -h, --help         Show this help text.
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
    --require-kubectl-cluster) REQUIRE_KUBECTL=true; REQUIRE_KUBECTL_CLUSTER=true ;;
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
shell_scripts=("$ROOT_DIR/deploy.sh")
while IFS= read -r -d '' script; do
  shell_scripts+=("$script")
done < <(find "$ROOT_DIR/k8s" "$ROOT_DIR/scripts" -type f -name '*.sh' -print0 2>/dev/null)
bash -n "${shell_scripts[@]}"

yaml_python=""
json_python=""
for candidate in python3 python; do
  if [[ -z $json_python ]] && command -v "$candidate" >/dev/null 2>&1; then
    json_python=$candidate
  fi
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import yaml' >/dev/null 2>&1; then
    yaml_python=$candidate
    break
  fi
done

validate_yaml_resources() {
  "$yaml_python" - "$@" <<'PY'
from pathlib import Path
import sys
import yaml

count = 0
for filename in sys.argv[1:]:
    path = Path(filename)
    for index, document in enumerate(yaml.safe_load_all(path.read_text()), start=1):
        if document is None:
            continue
        if not isinstance(document, dict):
            raise SystemExit(f"{path}:{index}: document must be a mapping")
        for field in ("apiVersion", "kind", "metadata"):
            if field not in document:
                raise SystemExit(f"{path}:{index}: missing {field}")
        metadata = document["metadata"]
        if not isinstance(metadata, dict) or not metadata.get("name"):
            raise SystemExit(f"{path}:{index}: missing metadata.name")
        count += 1
print(f"Validated {count} Kubernetes resources from {len(sys.argv) - 1} file(s).")
PY
}

validate_existing_secret_rollout() {
  "$yaml_python" - "$1" <<'PY'
from pathlib import Path
import sys
import yaml

expected_token = "deployment-validation"
documents = list(yaml.safe_load_all(Path(sys.argv[1]).read_text()))
deployments = {
    document.get("metadata", {}).get("labels", {}).get("app.kubernetes.io/component"):
        document.get("spec", {}).get("template", {}).get("metadata", {})
        .get("annotations", {}).get("tickety.io/existing-secret-rollout-token")
    for document in documents
    if isinstance(document, dict) and document.get("kind") == "Deployment"
}
expected = {"backend": expected_token, "worker": expected_token}
actual = {component: deployments.get(component) for component in expected}
if actual != expected:
    raise SystemExit(f"existing Secret rollout annotations are invalid: {actual}")
if any(isinstance(document, dict) and document.get("kind") == "Secret" for document in documents):
    raise SystemExit("existingSecret rendering must not create a chart-managed Secret")
print("Validated existing Secret rollout annotations.")
PY
}

rendered_files=()
existing_secret_render=""
temporary_dir=""
cleanup() {
  [[ -z $temporary_dir ]] || rm -rf "$temporary_dir"
}
trap cleanup EXIT

if require_or_skip "$REQUIRE_DOCKER" docker; then
  if ! docker compose version >/dev/null 2>&1; then
    echo "Docker Compose 2.24 or later is required (run it as 'docker compose')." >&2
    exit 1
  fi
  echo "Checking Docker Compose configuration..."
  docker compose --project-directory "$ROOT_DIR" -f "$ROOT_DIR/docker-compose.yml" config --quiet
  if [[ -n $json_python ]]; then
    docker compose --project-directory "$ROOT_DIR" -f "$ROOT_DIR/docker-compose.yml" config --format json |
      "$json_python" -c '
import json
import sys

model = json.load(sys.stdin)
services = model["services"]
expected = {"postgres", "migrate", "backend", "worker", "frontend"}
if not expected.issubset(services):
    raise SystemExit(f"missing Compose services: {sorted(expected - set(services))}")
for name, service in services.items():
    if name != "frontend" and service.get("ports"):
        raise SystemExit(f"{name} must not publish host ports")
if services["backend"]["depends_on"]["migrate"]["condition"] != "service_completed_successfully":
    raise SystemExit("backend must wait for successful migrations")
if services["worker"]["depends_on"]["migrate"]["condition"] != "service_completed_successfully":
    raise SystemExit("worker must wait for successful migrations")
if services["worker"]["environment"].get("TICKETY_PROCESS_ROLE") != "worker":
    raise SystemExit("worker process role is missing")
print("Validated Docker Compose service topology.")
'
  fi
fi

if require_or_skip "$REQUIRE_HELM" helm; then
  if [[ ! -f $CHART_DIR/Chart.yaml ]]; then
    echo "Helm chart is missing: $CHART_DIR" >&2
    exit 1
  fi

  echo "Linting Helm chart..."
  helm lint --strict --kube-version 1.25.0 "$CHART_DIR"

  temporary_dir=$(mktemp -d)
  render_chart() {
    local name=$1
    shift
    local output="$temporary_dir/$name.yaml"
    helm template tickety "$CHART_DIR" --namespace tickety --kube-version 1.25.0 "$@" >"$output"
    rendered_files+=("$output")
  }

  echo "Rendering Helm chart variants..."
  render_chart default
  render_chart production --values "$ROOT_DIR/deploy/examples/production-values.yaml"
  render_chart ingress --set ingress.enabled=true --set ingress.host=tickety.example.test
  render_chart backup --set backup.enabled=true
  render_chart external-database \
    --set postgresql.enabled=false \
    --set-string postgresql.externalDatabaseUrl='postgresql+psycopg2://tickety:password@database.example.test:5432/tickety'
  render_chart existing-secret \
    --set existingSecret=tickety-existing-secret \
    --set-string existingSecretRolloutToken=deployment-validation
  existing_secret_render="$temporary_dir/existing-secret.yaml"
fi

shopt -s nullglob
manifest_files=("$ROOT_DIR"/k8s/*.yaml)
if ((${#manifest_files[@]} == 0)); then
  echo "No Kubernetes manifests found in $ROOT_DIR/k8s." >&2
  exit 1
fi

if [[ -n $yaml_python ]]; then
  echo "Checking Kubernetes YAML resources..."
  if ((${#rendered_files[@]})); then
    validate_yaml_resources "${manifest_files[@]}" "${rendered_files[@]}"
    validate_existing_secret_rollout "$existing_secret_render"
  else
    validate_yaml_resources "${manifest_files[@]}"
  fi
elif [[ $REQUIRE_YAML == true ]]; then
  echo "Required YAML validator is unavailable: install PyYAML for python3 or python." >&2
  exit 1
else
  echo "Skipping YAML resource validation: PyYAML is unavailable."
fi

if require_or_skip "$REQUIRE_KUBECTL" kubectl; then
  if kubectl version --request-timeout=5s --output=json >/dev/null 2>&1; then
    echo "Validating Kubernetes manifests with kubectl client dry-run..."
    # Client-side schema validation downloads OpenAPI from the configured
    # cluster. YAML/resource checks above cover offline structure; disabling
    # this lookup keeps the dry-run focused on kubectl resource handling.
    kubectl apply --dry-run=client --validate=false -f "$ROOT_DIR/k8s"
    if ((${#rendered_files[@]})); then
      for rendered_file in "${rendered_files[@]}"; do
        kubectl apply --dry-run=client --validate=false -f "$rendered_file"
      done
    fi
  elif [[ $REQUIRE_KUBECTL_CLUSTER == true ]]; then
    echo "A reachable Kubernetes API server is required for kubectl client dry-run validation." >&2
    exit 1
  else
    echo "Skipping kubectl client dry-run: no reachable Kubernetes API server."
  fi
fi

echo "Deployment validation passed."
