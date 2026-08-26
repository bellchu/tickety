#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
readonly LOCAL_DOCKER_HOST=unix:///var/run/docker.sock
DOCKER=(docker --host "$LOCAL_DOCKER_HOST")
COMPOSE=("${DOCKER[@]}" compose --project-directory "$ROOT_DIR" -f "$ROOT_DIR/docker-compose.yml")

usage() {
  cat <<'EOF'
Usage:
  ./deploy.sh docker

The only supported production release path is Docker Compose to
https://tickety.nexora.com through the audited local Cloudflare Tunnel mapping.
No flags are accepted; configure reviewed production settings in .env.
EOF
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required command not found: $1" >&2
    exit 1
  fi
}

validate_local_docker_target() {
  local active_context
  local context_endpoint

  if [[ -n ${DOCKER_HOST:-} || -n ${DOCKER_CONTEXT:-} ]]; then
    echo "Docker production deployment rejected: DOCKER_HOST and DOCKER_CONTEXT overrides are forbidden." >&2
    exit 1
  fi
  if [[ ! -S /var/run/docker.sock ]]; then
    echo "Docker production deployment rejected: local Docker Unix socket is unavailable." >&2
    exit 1
  fi
  active_context=$(docker context show)
  context_endpoint=$(docker context inspect --format '{{.Endpoints.docker.Host}}' "$active_context")
  if [[ $context_endpoint != "$LOCAL_DOCKER_HOST" ]]; then
    echo "Docker production deployment rejected: active context $active_context targets $context_endpoint, not $LOCAL_DOCKER_HOST." >&2
    exit 1
  fi
  if ! "${DOCKER[@]}" info >/dev/null 2>&1; then
    echo "Docker production deployment rejected: local Docker Engine is unavailable." >&2
    exit 1
  fi
  echo "Local Docker target verified: context=$active_context endpoint=$context_endpoint."
}

require_clean_git_tree() {
  local worktree_status

  require_command git
  if ! git -C "$ROOT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "Docker production deployment requires an auditable Git worktree." >&2
    exit 1
  fi
  worktree_status=$(git -C "$ROOT_DIR" status --porcelain=v1 --untracked-files=normal)
  if [[ -n $worktree_status ]]; then
    echo "Docker production deployment rejected: the Git worktree is dirty." >&2
    echo "$worktree_status" >&2
    exit 1
  fi
}

require_expected_git_head() {
  local expected_full_sha=$1
  local current_full_sha

  current_full_sha=$(git -C "$ROOT_DIR" rev-parse HEAD)
  if [[ $current_full_sha != "$expected_full_sha" ]]; then
    echo "Docker production deployment rejected: Git HEAD changed during the build." >&2
    echo "Expected: $expected_full_sha" >&2
    echo "Current:  $current_full_sha" >&2
    exit 1
  fi
}

validate_docker_context_policy() {
  local pattern

  for pattern in '.env' '.env.*' 'backups/' '*.dump' '*.backup' '*.bak' '*.sql' '*.sql.gz'; do
    if ! grep -Fqx -- "$pattern" "$ROOT_DIR/.dockerignore"; then
      echo "Docker production deployment rejected: .dockerignore must exclude $pattern" >&2
      exit 1
    fi
  done
}

validate_backend_image_contents() {
  local backend_image=tickety-backend:latest
  local expected_image_id=$1
  local actual_image_id
  local configured_count

  configured_count=$("${COMPOSE[@]}" config --images | \
    grep -Fxc -- "$backend_image" || true)
  if [[ $configured_count != 3 ]]; then
    echo "Docker production deployment rejected: migrate, backend, and worker must share $backend_image." >&2
    exit 1
  fi
  if ! actual_image_id=$("${DOCKER[@]}" image inspect --format '{{.Id}}' "$backend_image" 2>/dev/null); then
    echo "Docker production deployment rejected: backend image was not built." >&2
    exit 1
  fi
  if [[ $actual_image_id != "$expected_image_id" ]]; then
    echo "Docker production deployment rejected: backend image tag changed after the audited build." >&2
    exit 1
  fi
  "${DOCKER[@]}" run --rm --entrypoint python "$expected_image_id" -c '
from pathlib import Path

root = Path("/app")
blocked = []
for path in root.rglob("*"):
    if not path.is_file():
        continue
    relative = path.relative_to(root)
    name = path.name
    if (
        "backups" in relative.parts
        or name == ".env"
        or (name.startswith(".env.") and name != ".env.example")
        or name.endswith((".dump", ".backup", ".bak", ".sql", ".sql.gz", ".db", ".sqlite"))
    ):
        blocked.append(str(relative))
if blocked:
    raise SystemExit("backend image contains files forbidden by the production context policy")
print("Backend image context verified: no environment files or database backups.")
'
}

validate_image_tag_id() {
  local image_tag=$1
  local expected_image_id=$2
  local actual_image_id

  if ! actual_image_id=$("${DOCKER[@]}" image inspect --format '{{.Id}}' "$image_tag" 2>/dev/null); then
    echo "Docker production deployment rejected: $image_tag was not built." >&2
    exit 1
  fi
  if [[ $actual_image_id != "$expected_image_id" ]]; then
    echo "Docker production deployment rejected: $image_tag changed after the audited build." >&2
    exit 1
  fi
}

deploy_docker() {
  local build_full_sha
  local backend_image_id
  local frontend_image_id
  require_command docker
  validate_local_docker_target
  if ! "${COMPOSE[@]}" version >/dev/null 2>&1; then
    echo "Docker Compose 2.24 or later is required (run it as 'docker compose')." >&2
    exit 1
  fi

  local build_sha
  local build_time
  local frontend_binding

  require_clean_git_tree
  validate_docker_context_policy
  build_full_sha=$(git -C "$ROOT_DIR" rev-parse HEAD)
  build_sha=$(git -C "$ROOT_DIR" rev-parse --short=12 HEAD)
  "$ROOT_DIR/scripts/verify-compose-production.sh" --mapping-only
  build_time=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  "${COMPOSE[@]}" build \
    --build-arg "BUILD_SHA=$build_sha" \
    --build-arg "BUILD_TIME=$build_time"
  backend_image_id=$("${DOCKER[@]}" image inspect --format '{{.Id}}' tickety-backend:latest)
  frontend_image_id=$("${DOCKER[@]}" image inspect --format '{{.Id}}' tickety-frontend:latest)
  validate_backend_image_contents "$backend_image_id"
  validate_image_tag_id tickety-frontend:latest "$frontend_image_id"
  require_clean_git_tree
  require_expected_git_head "$build_full_sha"
  "$ROOT_DIR/scripts/verify-compose-production.sh" --mapping-only
  validate_backend_image_contents "$backend_image_id"
  validate_image_tag_id tickety-frontend:latest "$frontend_image_id"
  "${COMPOSE[@]}" up --detach --no-build --wait
  "$ROOT_DIR/scripts/verify-compose-production.sh" \
    --expected-full-sha "$build_full_sha" \
    --expected-short-sha "$build_sha"
  frontend_binding=$("${COMPOSE[@]}" port frontend 3000)
  echo "Tickety production is verified at https://tickety.nexora.com (local binding $frontend_binding, build $build_sha)"
}

MODE=${1:-}
if [[ -z $MODE || $MODE == "-h" || $MODE == "--help" ]]; then
  usage
  exit 0
fi
shift

if [[ $MODE != docker ]]; then
  echo "Unsupported deployment mode: $MODE" >&2
  echo "Tickety production must use ./deploy.sh docker and the fixed Compose/Cloudflare mapping." >&2
  usage >&2
  exit 1
fi
if (($#)); then
  echo "The docker mode does not accept command-line options; use .env." >&2
  exit 1
fi

deploy_docker
