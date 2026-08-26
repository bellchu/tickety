#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
COMPOSE_FILE="$ROOT_DIR/docker-compose.yml"
readonly PRODUCTION_HOST=tickety.nexora.com
readonly PRODUCTION_URL=https://tickety.nexora.com
readonly LOCAL_DOCKER_HOST=unix:///var/run/docker.sock
EXPECTED_FULL_SHA=""
EXPECTED_SHORT_SHA=""
MAPPING_ONLY=false
SELF_TEST=false
PYTHON=""
DOCKER=(docker --host "$LOCAL_DOCKER_HOST")
COMPOSE=("${DOCKER[@]}" compose --project-directory "$ROOT_DIR" -f "$COMPOSE_FILE")

usage() {
  cat <<'EOF'
Usage:
  scripts/verify-compose-production.sh --mapping-only
  scripts/verify-compose-production.sh \
    --expected-full-sha FULL_GIT_SHA --expected-short-sha SHORT_GIT_SHA
  scripts/verify-compose-production.sh --self-test

Verify the fixed Tickety production path:
  https://tickety.nexora.com
    -> Cloudflare Tunnel
    -> https://localhost:443
    -> Compose tunnel-proxy
    -> frontend:3000

--mapping-only performs the read-only pre-deployment target and Compose topology
check. Full verification additionally proves runtime health, local and public
readiness/version metadata, the frontend BUILD_ID, and every public static asset.
No other production host or URL can be supplied.
EOF
}

die() {
  echo "Production verification failed: $*" >&2
  exit 1
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    die "required command not found: $1"
  fi
}

validate_local_docker_target() {
  local active_context
  local context_endpoint

  require_command docker
  if [[ -n ${DOCKER_HOST:-} || -n ${DOCKER_CONTEXT:-} ]]; then
    die "DOCKER_HOST and DOCKER_CONTEXT overrides are forbidden for production"
  fi
  if [[ ! -S /var/run/docker.sock ]]; then
    die "local Docker Unix socket is unavailable"
  fi
  active_context=$(docker context show)
  context_endpoint=$(docker context inspect --format '{{.Endpoints.docker.Host}}' "$active_context")
  if [[ $context_endpoint != "$LOCAL_DOCKER_HOST" ]]; then
    die "active Docker context $active_context targets $context_endpoint, not $LOCAL_DOCKER_HOST"
  fi
  if ! "${DOCKER[@]}" info >/dev/null 2>&1; then
    die "local Docker Engine is unavailable"
  fi
  echo "Local Docker target verified: context=$active_context endpoint=$context_endpoint."
}

find_python() {
  local candidate
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      PYTHON=$candidate
      return
    fi
  done
  die "required command not found: python3 or python"
}

hash_stream() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum | awk '{print $1}'
  else
    shasum -a 256 | awk '{print $1}'
  fi
}

validate_sha_pair() {
  local full_sha=$1
  local short_sha=$2

  if [[ ! $full_sha =~ ^[0-9a-f]{40}$ ]]; then
    echo "Expected full Git SHA must be exactly 40 lowercase hexadecimal characters." >&2
    return 1
  fi
  if [[ ! $short_sha =~ ^[0-9a-f]{12}$ ]]; then
    echo "Expected short Git SHA must be exactly 12 lowercase hexadecimal characters." >&2
    return 1
  fi
  if [[ ${full_sha:0:12} != "$short_sha" ]]; then
    echo "Expected short Git SHA is not the first 12 characters of the full SHA." >&2
    return 1
  fi
}

validate_tunnel_config_line() {
  local config_line=$1

  "$PYTHON" - "$config_line" "$PRODUCTION_HOST" <<'PY'
import json
import sys

line, expected_host = sys.argv[1:]
marker = "config="
if marker not in line:
    raise SystemExit("Cloudflare configuration evidence has no config payload")
payload = line.split(marker, 1)[1].lstrip()
try:
    encoded, _ = json.JSONDecoder().raw_decode(payload)
    config = json.loads(encoded) if isinstance(encoded, str) else encoded
except (json.JSONDecodeError, TypeError) as exc:
    raise SystemExit(f"Cloudflare configuration evidence is malformed: {exc}")

if not isinstance(config, dict):
    raise SystemExit("Cloudflare configuration payload must be an object")
ingress = config.get("ingress")
if not isinstance(ingress, list) or len(ingress) != 2:
    raise SystemExit("Cloudflare ingress must contain exactly the production rule and 404 fallback")
production, fallback = ingress
if not isinstance(production, dict) or not isinstance(fallback, dict):
    raise SystemExit("Cloudflare ingress rules must be objects")
if production.get("hostname") != expected_host:
    raise SystemExit(f"Cloudflare hostname is not the fixed production host {expected_host}")
if production.get("service") != "https://localhost:443":
    raise SystemExit("Cloudflare production origin is not https://localhost:443")
origin_request = production.get("originRequest")
if not isinstance(origin_request, dict) or origin_request.get("noTLSVerify") is not True:
    raise SystemExit("Cloudflare production origin must explicitly allow the Caddy internal certificate")
if fallback.get("service") != "http_status:404" or fallback.get("hostname") is not None:
    raise SystemExit("Cloudflare ingress must end with an unscoped 404 fallback")
if any(rule.get("hostname") not in (None, expected_host) for rule in ingress):
    raise SystemExit("Cloudflare ingress contains an unexpected hostname")
PY
}

validate_readiness_json() {
  local body=$1
  local source=$2

  "$PYTHON" - "$body" "$source" <<'PY'
import json
import sys

raw, source = sys.argv[1:]
try:
    body = json.loads(raw)
except json.JSONDecodeError as exc:
    raise SystemExit(f"{source} readiness is not JSON: {exc}")
if body.get("status") != "ready":
    raise SystemExit(f"{source} readiness is not ready: {body!r}")
checks = body.get("checks")
if not isinstance(checks, dict) or checks.get("database") != "ok":
    raise SystemExit(f"{source} readiness does not prove database availability: {body!r}")
PY
}

validate_version_json() {
  local body=$1
  local source=$2
  local expected_short_sha=$3

  "$PYTHON" - "$body" "$source" "$expected_short_sha" <<'PY'
import json
import sys

raw, source, expected_sha = sys.argv[1:]
try:
    body = json.loads(raw)
except json.JSONDecodeError as exc:
    raise SystemExit(f"{source} version is not JSON: {exc}")
if body.get("component") != "backend":
    raise SystemExit(f"{source} version is not backend build evidence: {body!r}")
if body.get("build_sha") != expected_sha:
    raise SystemExit(
        f"{source} build SHA {body.get('build_sha')!r} does not match {expected_sha}"
    )
build_time = body.get("build_time")
version = body.get("version")
if not isinstance(build_time, str) or not build_time:
    raise SystemExit(f"{source} build timestamp is missing")
if not isinstance(version, str) or not version:
    raise SystemExit(f"{source} application version is missing")
print(f"{body['build_sha']}\t{build_time}\t{version}")
PY
}

validate_compose_mapping() {
  validate_local_docker_target
  if ! "${COMPOSE[@]}" version >/dev/null 2>&1; then
    die "Docker Compose v2 is required"
  fi

  "${COMPOSE[@]}" config --quiet
  "$PYTHON" - "$ROOT_DIR" "$PRODUCTION_URL" \
    3< <("${COMPOSE[@]}" config --format json) <<'PY'
import json
import os
from pathlib import Path
import sys
from urllib.parse import unquote, urlsplit

root = Path(sys.argv[1]).resolve()
production_url = sys.argv[2]
with os.fdopen(3) as config_stream:
    model = json.load(config_stream)
if model.get("name") != "tickety":
    raise SystemExit("Compose production project name must be tickety")
services = model.get("services", {})
expected_services = {"postgres", "migrate", "backend", "worker", "frontend", "tunnel-proxy"}
if set(services) != expected_services:
    raise SystemExit(f"Compose services differ from the fixed topology: {sorted(services)}")

for name in ("migrate", "backend", "worker"):
    if services[name].get("image") != "tickety-backend:latest":
        raise SystemExit(f"{name} must use the freshly built tickety-backend image")
if services["frontend"].get("image") != "tickety-frontend:latest":
    raise SystemExit("frontend must use the freshly built tickety-frontend image")

for name, service in services.items():
    if name not in {"frontend", "tunnel-proxy"} and service.get("ports"):
        raise SystemExit(f"Compose service {name} must not publish a host port")

frontend_ports = services["frontend"].get("ports") or []
if len(frontend_ports) != 1:
    raise SystemExit("frontend must publish exactly one loopback development port")
frontend_port = frontend_ports[0]
if (
    frontend_port.get("mode") != "ingress"
    or frontend_port.get("target") != 3000
    or frontend_port.get("protocol") != "tcp"
    or frontend_port.get("host_ip") != "127.0.0.1"
):
    raise SystemExit("frontend host port must bind TCP 3000 to IPv4 loopback only")

tunnel_ports = services["tunnel-proxy"].get("ports") or []
expected_tunnel_port = {
    "mode": "ingress",
    "target": 443,
    "published": "443",
    "protocol": "tcp",
    "host_ip": "127.0.0.1",
}
if tunnel_ports != [expected_tunnel_port]:
    raise SystemExit("tunnel-proxy must bind host TCP 443 to IPv4 loopback only")

def dependency(service, dependency):
    return services[service].get("depends_on", {}).get(dependency, {}).get("condition")

if dependency("tunnel-proxy", "frontend") != "service_healthy":
    raise SystemExit("tunnel-proxy must wait for a healthy frontend")
if dependency("frontend", "backend") != "service_healthy":
    raise SystemExit("frontend must wait for a healthy backend")
for name in ("backend", "worker"):
    if dependency(name, "migrate") != "service_completed_successfully":
        raise SystemExit(f"{name} must wait for successful migrations")

backend_env = services["backend"].get("environment", {})
frontend_env = services["frontend"].get("environment", {})
required_backend_env = {
    "APP_MODE": "production",
    "TICKETY_DEPLOYMENT_CLASS": "production",
    "FRONTEND_URL": production_url,
    "CORS_ALLOW_ORIGINS": production_url,
    "LOGIN_REQUIRED": "true",
    "COOKIE_SECURE": "true",
}
for key, expected in required_backend_env.items():
    if backend_env.get(key) != expected:
        raise SystemExit(f"backend {key} must be {expected!r} for production")
if frontend_env.get("SITE_URL") != production_url:
    raise SystemExit("frontend SITE_URL must be the fixed production URL")
if frontend_env.get("BACKEND_URL") != "http://backend:8000":
    raise SystemExit("frontend must proxy to the private Compose backend")

postgres_env = services["postgres"].get("environment", {})
postgres_user = str(postgres_env.get("POSTGRES_USER") or "")
postgres_password = str(postgres_env.get("POSTGRES_PASSWORD") or "")
postgres_database = str(postgres_env.get("POSTGRES_DB") or "")
if (
    not postgres_user
    or not postgres_database
    or len(postgres_password) < 32
    or postgres_password == "tickety"
):
    raise SystemExit(
        "production PostgreSQL credentials must be explicit and the password "
        "must be a non-default value of at least 32 characters"
    )

database_urls = {
    name: str(services[name].get("environment", {}).get("DATABASE_URL") or "")
    for name in ("migrate", "backend", "worker")
}
if len(set(database_urls.values())) != 1:
    raise SystemExit("migrate, backend, and worker must use one DATABASE_URL")
database_url = next(iter(database_urls.values()))
parsed_database_url = urlsplit(database_url)
try:
    database_port = parsed_database_url.port
except ValueError as exc:
    raise SystemExit("production DATABASE_URL has an invalid port") from exc
if (
    parsed_database_url.scheme != "postgresql+psycopg2"
    or parsed_database_url.query
    or parsed_database_url.fragment
    or unquote(parsed_database_url.username or "") != postgres_user
    or unquote(parsed_database_url.password or "") != postgres_password
    or parsed_database_url.hostname != "postgres"
    or database_port != 5432
    or unquote(parsed_database_url.path.lstrip("/")) != postgres_database
):
    raise SystemExit(
        "production DATABASE_URL must exactly match the private Compose "
        "PostgreSQL service and POSTGRES_* credentials, without query or fragment overrides"
    )

expected_caddy_source = root / "deploy/local-tunnel/Caddyfile"
mounts = services["tunnel-proxy"].get("volumes") or []
matches = [
    mount
    for mount in mounts
    if mount.get("target") == "/etc/caddy/Caddyfile"
]
if len(matches) != 1:
    raise SystemExit("tunnel-proxy must mount exactly one Caddyfile")
mount = matches[0]
if (
    mount.get("type") != "bind"
    or Path(mount.get("source", "")).resolve() != expected_caddy_source
    or mount.get("read_only") is not True
):
    raise SystemExit("tunnel-proxy Caddyfile must be the audited read-only repository file")
PY

  "$PYTHON" - "$ROOT_DIR/deploy/local-tunnel/Caddyfile" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
lines = [
    line.strip()
    for line in path.read_text().splitlines()
    if line.strip() and not line.lstrip().startswith("#")
]
expected = [
    "{",
    "auto_https disable_redirects",
    "}",
    "https://localhost, https://tickety.nexora.com {",
    "tls internal",
    "reverse_proxy frontend:3000",
    "}",
]
if lines != expected:
    raise SystemExit("Caddyfile contains directives outside the fixed production proxy path")
PY

  echo "Compose production topology verified: tunnel-proxy -> frontend:3000."
}

validate_cloudflare_mapping() {
  local cloudflared_pid
  local config_line

  require_command systemctl
  require_command journalctl
  if ! systemctl is-active --quiet cloudflared; then
    die "cloudflared.service is not active"
  fi
  cloudflared_pid=$(systemctl show cloudflared --property ExecMainPID --value)
  if [[ ! $cloudflared_pid =~ ^[1-9][0-9]*$ ]]; then
    die "cloudflared.service has no auditable running PID"
  fi
  config_line=$(journalctl --unit cloudflared --no-pager --output cat \
    "_PID=$cloudflared_pid" | awk '/Updated to new configuration/{line=$0} END{print line}')
  if [[ -z $config_line ]]; then
    die "current cloudflared process has no applied remote configuration evidence"
  fi
  if ! validate_tunnel_config_line "$config_line"; then
    die "cloudflared remote mapping does not match the fixed production path"
  fi

  echo "Cloudflare production mapping verified: $PRODUCTION_HOST -> https://localhost:443 (pid=$cloudflared_pid)."
  echo "Cloudflare configuration evidence: $config_line"
}

compose_container_id() {
  local service=$1
  local ids
  local -a containers=()

  ids=$("${COMPOSE[@]}" ps --all --quiet "$service")
  if [[ -n $ids ]]; then
    mapfile -t containers <<<"$ids"
  fi
  if ((${#containers[@]} != 1)); then
    die "expected exactly one Compose container for $service; found ${#containers[@]}"
  fi
  printf '%s' "${containers[0]}"
}

validate_applied_compose_config() {
  local service=$1
  local container_id=$2
  local expected_config_hash
  local actual_config_hash

  expected_config_hash=$("${COMPOSE[@]}" config --hash "$service" | \
    awk -v expected="$service" '$1 == expected {print $2}')
  actual_config_hash=$("${DOCKER[@]}" inspect --format \
    '{{index .Config.Labels "com.docker.compose.config-hash"}}' "$container_id")
  if [[ -z $expected_config_hash || $actual_config_hash != "$expected_config_hash" ]]; then
    die "$service container does not use the current audited Compose configuration"
  fi
  echo "Compose config evidence: service=$service config_hash=$actual_config_hash."
}

validate_running_service() {
  local service=$1
  local container_id
  local evidence

  container_id=$(compose_container_id "$service")
  evidence=$("${DOCKER[@]}" inspect --format \
    '{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}|{{.State.ExitCode}}' \
    "$container_id")
  if [[ $evidence != 'running|healthy|0' ]]; then
    die "$service is not running and healthy: $evidence"
  fi
  validate_applied_compose_config "$service" "$container_id"
  echo "Compose service healthy: $service container=$container_id."
}

validate_runtime_health() {
  local service
  local migrate_container
  local migrate_evidence

  for service in postgres backend worker frontend tunnel-proxy; do
    validate_running_service "$service"
  done
  migrate_container=$(compose_container_id migrate)
  migrate_evidence=$("${DOCKER[@]}" inspect --format \
    '{{.State.Status}}|{{.State.ExitCode}}' "$migrate_container")
  if [[ $migrate_evidence != 'exited|0' ]]; then
    die "migrate did not complete successfully: $migrate_evidence"
  fi
  validate_applied_compose_config migrate "$migrate_container"
  echo "Compose migration completed: container=$migrate_container exit=0."
}

validate_backend_image_metadata() {
  local service
  local container_id
  local image_id
  local image_environment
  local build_sha
  local build_time

  for service in backend worker migrate; do
    container_id=$(compose_container_id "$service")
    image_id=$("${DOCKER[@]}" inspect --format '{{.Image}}' "$container_id")
    image_environment=$("${DOCKER[@]}" image inspect --format \
      '{{range .Config.Env}}{{println .}}{{end}}' "$image_id")
    build_sha=$(awk -F= '$1 == "TICKETY_BUILD_SHA" {print substr($0, index($0, "=") + 1)}' \
      <<<"$image_environment")
    build_time=$(awk -F= '$1 == "TICKETY_BUILD_TIME" {print substr($0, index($0, "=") + 1)}' \
      <<<"$image_environment")
    if [[ $build_sha != "$EXPECTED_SHORT_SHA" || -z $build_time ]]; then
      die "$service image metadata does not match expected build $EXPECTED_SHORT_SHA"
    fi
    echo "Image build evidence: service=$service image=$image_id build_sha=$build_sha build_time=$build_time."
  done
}

local_fetch() {
  local path=$1
  curl --insecure --fail --silent --show-error --globoff \
    --connect-timeout 5 --max-time 20 \
    --noproxy "$PRODUCTION_HOST" \
    --resolve "$PRODUCTION_HOST:443:127.0.0.1" \
    "$PRODUCTION_URL$path"
}

public_fetch() {
  local path=$1
  curl --fail --silent --show-error --globoff \
    --connect-timeout 5 --max-time 20 "$PRODUCTION_URL$path"
}

validate_source_state() {
  local current_full_sha
  local current_short_sha
  local worktree_status

  require_command git
  validate_sha_pair "$EXPECTED_FULL_SHA" "$EXPECTED_SHORT_SHA" || \
    die "expected Git SHA evidence is invalid"
  current_full_sha=$(git -C "$ROOT_DIR" rev-parse HEAD)
  current_short_sha=$(git -C "$ROOT_DIR" rev-parse --short=12 HEAD)
  if [[ $current_full_sha != "$EXPECTED_FULL_SHA" || $current_short_sha != "$EXPECTED_SHORT_SHA" ]]; then
    die "repository HEAD changed during deployment (current=$current_full_sha expected=$EXPECTED_FULL_SHA)"
  fi
  worktree_status=$(git -C "$ROOT_DIR" status --porcelain=v1 --untracked-files=normal)
  if [[ -n $worktree_status ]]; then
    echo "$worktree_status" >&2
    die "repository worktree is dirty; build metadata would not identify its contents"
  fi
  echo "Source evidence verified: full_sha=$EXPECTED_FULL_SHA short_sha=$EXPECTED_SHORT_SHA worktree=clean."
}

validate_runtime_endpoints() {
  local local_readiness
  local public_readiness
  local local_version
  local public_version
  local local_build_evidence
  local public_build_evidence

  local_readiness=$(local_fetch /api/health/ready)
  public_readiness=$(public_fetch /api/health/ready)
  validate_readiness_json "$local_readiness" "local tunnel origin"
  validate_readiness_json "$public_readiness" "public production"

  local_version=$(local_fetch /api/version)
  public_version=$(public_fetch /api/version)
  local_build_evidence=$(validate_version_json \
    "$local_version" "local tunnel origin" "$EXPECTED_SHORT_SHA")
  public_build_evidence=$(validate_version_json \
    "$public_version" "public production" "$EXPECTED_SHORT_SHA")
  if [[ $local_build_evidence != "$public_build_evidence" ]]; then
    die "local and public version evidence differ"
  fi

  echo "Local readiness evidence: $local_readiness"
  echo "Public readiness evidence: $public_readiness"
  echo "Production version evidence: $public_version"
}

validate_frontend_assets() {
  local frontend_container
  local build_id
  local asset_path
  local relative_path
  local public_path
  local internal_sha
  local external_sha
  local internal_manifest=""
  local external_manifest=""
  local internal_manifest_sha
  local external_manifest_sha
  local -a asset_paths=()

  frontend_container=$(compose_container_id frontend)
  build_id=$("${DOCKER[@]}" exec "$frontend_container" cat /app/.next/BUILD_ID)
  if [[ $build_id != "$EXPECTED_SHORT_SHA" ]]; then
    die "frontend BUILD_ID $build_id does not match expected SHA $EXPECTED_SHORT_SHA"
  fi

  mapfile -d '' -t asset_paths < <(
    "${DOCKER[@]}" exec "$frontend_container" find /app/.next/static -type f -print0 | LC_ALL=C sort -z
  )
  if ((${#asset_paths[@]} == 0)); then
    die "frontend image has no public static assets"
  fi
  for asset_path in "${asset_paths[@]}"; do
    if [[ $asset_path != /app/.next/static/* || $asset_path == *$'\n'* || $asset_path == *$'\r'* || $asset_path == */../* || $asset_path == */.. ]]; then
      die "unsafe frontend asset path: $asset_path"
    fi
    relative_path=${asset_path#/app/.next}
    public_path="/_next$relative_path"
    internal_sha=$("${DOCKER[@]}" exec "$frontend_container" sha256sum "$asset_path" | awk '{print $1}')
    external_sha=$(public_fetch "$public_path" | hash_stream)
    internal_manifest+="$public_path $internal_sha"$'\n'
    external_manifest+="$public_path $external_sha"$'\n'
    if [[ $internal_sha != "$external_sha" ]]; then
      die "public frontend asset does not match the running image: $public_path"
    fi
  done

  internal_manifest_sha=$(printf '%s' "$internal_manifest" | hash_stream)
  external_manifest_sha=$(printf '%s' "$external_manifest" | hash_stream)
  if [[ $internal_manifest_sha != "$external_manifest_sha" ]]; then
    die "public frontend asset manifest does not match the running image"
  fi
  echo "Frontend evidence verified: container=$frontend_container build_id=$build_id assets=${#asset_paths[@]} asset_set_sha256=$internal_manifest_sha."
}

validate_frontend_document() {
  local local_document
  local public_document
  local local_sha
  local public_sha

  local_document=$(local_fetch /)
  public_document=$(public_fetch /)
  if [[ $local_document != *'<html'* || $local_document != *'/_next/static/'* ]]; then
    die "local frontend document is not a rendered Next.js application shell"
  fi
  if [[ $public_document != *'<html'* || $public_document != *'/_next/static/'* ]]; then
    die "public frontend document is not a rendered Next.js application shell"
  fi
  local_sha=$(printf '%s' "$local_document" | hash_stream)
  public_sha=$(printf '%s' "$public_document" | hash_stream)
  if [[ $local_sha != "$public_sha" ]]; then
    die "public frontend document does not match the local audited tunnel origin"
  fi
  echo "Frontend document evidence verified: local_public_sha256=$local_sha."
}

expect_failure() {
  if "$@" >/dev/null 2>&1; then
    echo "Self-test expected failure but command passed: $*" >&2
    return 1
  fi
}

self_test() {
  local full_sha=0123456789abcdef0123456789abcdef01234567
  local short_sha=0123456789ab
  local ready='{"status":"ready","checks":{"database":"ok"}}'
  local version='{"component":"backend","version":"1.0.0","build_sha":"0123456789ab","build_time":"2026-08-26T00:00:00Z"}'
  local good_mapping='config={"ingress":[{"hostname":"tickety.nexora.com","originRequest":{"noTLSVerify":true},"service":"https://localhost:443"},{"service":"http_status:404"}]} version=1'

  validate_sha_pair "$full_sha" "$short_sha" >/dev/null
  expect_failure validate_sha_pair "$full_sha" deadbeefdead
  validate_readiness_json "$ready" self-test >/dev/null
  expect_failure validate_readiness_json '{"status":"starting"}' self-test
  validate_version_json "$version" self-test "$short_sha" >/dev/null
  expect_failure validate_version_json "$version" self-test deadbeefdead
  validate_tunnel_config_line "$good_mapping" >/dev/null
  expect_failure validate_tunnel_config_line \
    "${good_mapping/tickety.nexora.com/not-production.invalid}"
  expect_failure validate_tunnel_config_line \
    "${good_mapping/https:\/\/localhost:443/http:\/\/localhost:3000}"
  expect_failure validate_tunnel_config_line \
    "${good_mapping/\"noTLSVerify\":true/\"noTLSVerify\":false}"

  echo "Compose production verifier self-test passed."
}

while (($#)); do
  case "$1" in
    --expected-full-sha)
      EXPECTED_FULL_SHA=${2:?--expected-full-sha requires a value}
      shift 2
      ;;
    --expected-short-sha)
      EXPECTED_SHORT_SHA=${2:?--expected-short-sha requires a value}
      shift 2
      ;;
    --mapping-only)
      MAPPING_ONLY=true
      shift
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

find_python

if [[ $SELF_TEST == true ]]; then
  if [[ $MAPPING_ONLY == true || -n $EXPECTED_FULL_SHA || -n $EXPECTED_SHORT_SHA ]]; then
    die "--self-test does not accept mapping or SHA options"
  fi
  self_test
  exit 0
fi

if [[ $MAPPING_ONLY == true ]]; then
  if [[ -n $EXPECTED_FULL_SHA || -n $EXPECTED_SHORT_SHA ]]; then
    die "--mapping-only does not accept SHA options"
  fi
  validate_compose_mapping
  validate_cloudflare_mapping
  echo "Compose production mapping preflight passed for $PRODUCTION_URL."
  exit 0
fi

if [[ -z $EXPECTED_FULL_SHA || -z $EXPECTED_SHORT_SHA ]]; then
  die "full verification requires --expected-full-sha and --expected-short-sha"
fi

require_command curl
require_command docker
if ! command -v sha256sum >/dev/null 2>&1 && ! command -v shasum >/dev/null 2>&1; then
  die "required command not found: sha256sum or shasum"
fi

validate_source_state
validate_compose_mapping
validate_cloudflare_mapping
validate_runtime_health
validate_backend_image_metadata
validate_runtime_endpoints
validate_frontend_document
validate_frontend_assets

echo "Compose production verified: url=$PRODUCTION_URL full_sha=$EXPECTED_FULL_SHA short_sha=$EXPECTED_SHORT_SHA."
