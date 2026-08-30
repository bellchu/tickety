#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
: "${TICKETY_DEV_NAMESPACE:?set TICKETY_DEV_NAMESPACE}"
: "${TICKETY_DEV_PUBLIC_HOST:?set TICKETY_DEV_PUBLIC_HOST}"
: "${TICKETY_DEV_REGISTRY:?set TICKETY_DEV_REGISTRY}"
readonly NAMESPACE=$TICKETY_DEV_NAMESPACE PUBLIC_HOST=$TICKETY_DEV_PUBLIC_HOST
readonly REGISTRY=$TICKETY_DEV_REGISTRY
export TICKETY_DEV_NAMESPACE TICKETY_DEV_PUBLIC_HOST TICKETY_DEV_REGISTRY
KUBECTL=(microk8s kubectl)

die() { echo "Dev release failed: $*" >&2; exit 1; }

normalize_docker_image_id() {
  local image_id=${1#sha256:}
  [[ $image_id =~ ^[0-9a-f]{12,64}$ ]] || return 1
  printf '%s\n' "$image_id"
}

is_tickety_dev_job_name() {
  [[ $1 =~ ^tickety-(backup|migrate)-dev-[0-9a-f]{12}$ ]]
}

is_tickety_dev_image_ref() {
  [[ $1 =~ ^localhost:32000/tickety-(backend|frontend):dev-[0-9a-f]{12}$ ]]
}

cleanup_tickety_completed_release_jobs_and_images() {
  local current_backend current_frontend current_short job_name succeeded
  local image_ref image_digest digest_ref repository job_inventory image_inventory
  local -a stale_refs=()
  declare -A stale_digest_refs=() live_digests=()

  current_backend=$("${KUBECTL[@]}" -n "$NAMESPACE" get deployment backend \
    -o jsonpath='{.spec.template.spec.containers[?(@.name=="backend")].image}')
  current_frontend=$("${KUBECTL[@]}" -n "$NAMESPACE" get deployment frontend \
    -o jsonpath='{.spec.template.spec.containers[?(@.name=="frontend")].image}')
  is_tickety_dev_image_ref "$current_backend" || die "current backend image is not an immutable dev release"
  is_tickety_dev_image_ref "$current_frontend" || die "current frontend image is not an immutable dev release"
  current_short=${current_backend##*:dev-}
  [[ ${current_frontend##*:dev-} == "$current_short" ]] || \
    die "current backend and frontend releases differ"

  job_inventory=$("${KUBECTL[@]}" -n "$NAMESPACE" get jobs \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.succeeded}{"\n"}{end}')
  while IFS=$'\t' read -r job_name succeeded; do
    is_tickety_dev_job_name "$job_name" || continue
    [[ $succeeded == 1 && $job_name != *"-$current_short" ]] || continue
    "${KUBECTL[@]}" -n "$NAMESPACE" delete job "$job_name" --wait=true
  done <<<"$job_inventory"

  image_inventory=$(microk8s ctr images list)
  while read -r image_ref _ image_digest _; do
    is_tickety_dev_image_ref "$image_ref" || continue
    [[ $image_ref != "$current_backend" && $image_ref != "$current_frontend" ]] || continue
    [[ $image_digest =~ ^sha256:[0-9a-f]{64}$ ]] || die "invalid Tickety dev image digest"
    stale_refs+=("$image_ref")
    repository=${image_ref%:dev-*}
    stale_digest_refs["$repository@$image_digest"]=present
  done <<<"$image_inventory"

  ((${#stale_refs[@]} == 0)) || microk8s ctr images rm "${stale_refs[@]}"
  image_inventory=$(microk8s ctr images list)
  while read -r image_ref _ image_digest _; do
    [[ $image_ref != *@sha256:* ]] || continue
    live_digests["$image_digest"]=present
  done <<<"$image_inventory"
  for digest_ref in "${!stale_digest_refs[@]}"; do
    image_digest=${digest_ref##*@}
    [[ -z ${live_digests[$image_digest]+present} ]] || continue
    if microk8s ctr images list | awk '{print $1}' | grep -Fxq "$digest_ref"; then
      microk8s ctr images rm "$digest_ref"
    fi
  done
}

wait_for_audited_build_space() {
  local available_kib attempt
  for attempt in {1..20}; do
    available_kib=$(df --output=avail -k / | tail -n 1 | tr -d ' ')
    if [[ $available_kib =~ ^[0-9]+$ && $available_kib -ge 8388608 ]]; then
      return 0
    fi
    sleep 1
  done
  die "at least 8 GiB free disk is required for an audited build"
}

available_root_kib() {
  df --output=avail -k / | tail -n 1 | tr -d ' '
}

garbage_collect_tickety_registry() {
  "${KUBECTL[@]}" -n container-registry get deployment registry >/dev/null
  [[ $("${KUBECTL[@]}" -n container-registry get deployment registry \
    -o jsonpath='{.spec.replicas}') == 1 ]] || die "shared registry must have exactly one replica"
  [[ $("${KUBECTL[@]}" -n container-registry get pvc registry-claim \
    -o jsonpath='{.status.phase}') == Bound ]] || die "shared registry PVC is not bound"

  restore_registry_after_gc_failure() {
    "${KUBECTL[@]}" -n container-registry scale deployment/registry \
      --replicas=1 >/dev/null || true
    "${KUBECTL[@]}" -n container-registry rollout status deployment/registry \
      --timeout=3m >/dev/null || true
  }
  "${KUBECTL[@]}" -n container-registry delete job tickety-registry-gc \
    --ignore-not-found=true --wait=true
  "${KUBECTL[@]}" -n container-registry scale deployment/registry --replicas=0
  if ! "${KUBECTL[@]}" -n container-registry wait --for=delete pod \
    --selector app=registry --timeout=3m; then
    restore_registry_after_gc_failure
    die "shared registry did not stop for garbage collection"
  fi
  if ! "${KUBECTL[@]}" apply -f - <<'YAML'
apiVersion: batch/v1
kind: Job
metadata:
  name: tickety-registry-gc
  namespace: container-registry
spec:
  activeDeadlineSeconds: 600
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: garbage-collect
          image: registry:2.8.3
          command:
            - /bin/registry
            - garbage-collect
            - --delete-untagged
            - /etc/docker/registry/config.yml
          volumeMounts:
            - name: registry-data
              mountPath: /var/lib/registry
      volumes:
        - name: registry-data
          persistentVolumeClaim:
            claimName: registry-claim
YAML
  then
    restore_registry_after_gc_failure
    die "shared registry garbage-collection job could not be created"
  fi
  if ! "${KUBECTL[@]}" -n container-registry wait --for=condition=complete \
    job/tickety-registry-gc --timeout=10m; then
    "${KUBECTL[@]}" -n container-registry logs --tail=200 \
      job/tickety-registry-gc || true
    restore_registry_after_gc_failure
    die "shared registry garbage collection failed"
  fi
  "${KUBECTL[@]}" -n container-registry delete job tickety-registry-gc --wait=true || {
    restore_registry_after_gc_failure
    die "shared registry garbage-collection job could not be removed"
  }
  "${KUBECTL[@]}" -n container-registry scale deployment/registry --replicas=1 || {
    restore_registry_after_gc_failure
    die "shared registry could not be restored"
  }
  "${KUBECTL[@]}" -n container-registry rollout status deployment/registry \
    --timeout=3m || {
    restore_registry_after_gc_failure
    die "shared registry did not become ready after garbage collection"
  }
  curl --fail --silent --show-error --max-time 20 "$REGISTRY/v2/" >/dev/null
  echo "Tickety registry garbage collection completed."
}

prune_tickety_registry_manifests() {
  local current_short=$1 deleted
  deleted=$(python3 "$ROOT_DIR/deploy/dev-microk8s/prune-registry.py" \
    --registry "http://127.0.0.1:32000" \
    --keep-backend "dev-$current_short" \
    --keep-frontend "dev-$current_short" \
    --delete)
  [[ $deleted =~ ^[0-9]+$ ]] || die "registry prune returned an invalid deletion count"
  printf '%s\n' "$deleted"
}

cleanup_tickety_build_images() {
  local image_filter image_id normalized_image_id parent_id repo_tags is_root
  local -a image_ids=()
  declare -A seen=()
  while IFS= read -r image_id; do
    is_root=true
    while normalized_image_id=$(normalize_docker_image_id "$image_id"); do
      [[ -z ${seen[$normalized_image_id]+present} ]] || break
      if [[ $is_root != true ]]; then
        repo_tags=$(docker image inspect --format '{{json .RepoTags}}' \
          "$normalized_image_id") || break
        [[ $repo_tags == null || $repo_tags == '[]' ]] || break
      fi
      image_ids+=("$normalized_image_id")
      seen[$normalized_image_id]=present
      parent_id=$(docker image inspect --format '{{.Parent}}' \
        "$normalized_image_id") || break
      [[ -n $parent_id ]] || break
      image_id=$parent_id
      is_root=false
    done
  done < <(
    for image_filter in \
      "label=com.tickety.dev=true" \
      "label=com.tickety.build-stage=frontend"; do
      # Multi-stage builder images can be hidden while a runtime image still
      # references them. Include intermediate records before deleting either
      # chain so their audited ancestry is not orphaned.
      docker image ls --all --quiet --no-trunc --filter "$image_filter"
    done
  )
  for image_id in "${image_ids[@]}"; do
    if [[ -n $(docker ps --quiet --filter "ancestor=$image_id") ]]; then
      die "a running Docker container still uses a Tickety dev build image"
    fi
  done
  for image_id in "${image_ids[@]}"; do
    if docker image inspect "$image_id" >/dev/null 2>&1; then
      # Delete only the explicitly audited node. Docker's implicit parent
      # pruning races when another audited chain already removed a shared
      # parent; the collected chain below owns parent deletion deterministically.
      docker image rm --no-prune "$image_id"
    fi
  done
  docker image prune --force --filter "label=com.tickety.dev=true"
  docker image prune --force \
    --filter "label=com.tickety.build-stage=frontend"
}

if [[ ${1:-} == --self-test ]]; then
  [[ $NAMESPACE == tickety && $PUBLIC_HOST == dev.tickety.example && $REGISTRY == localhost:32000 ]]
  test_image_id=$(printf 'a%.0s' {1..64})
  [[ $(normalize_docker_image_id "sha256:$test_image_id") == "$test_image_id" ]]
  ! normalize_docker_image_id 'not-an-image-id'
  is_tickety_dev_job_name 'tickety-migrate-dev-0123456789ab'
  is_tickety_dev_job_name 'tickety-backup-dev-abcdef012345'
  ! is_tickety_dev_job_name 'tickety-migrate-routing-0123456789ab'
  is_tickety_dev_image_ref 'localhost:32000/tickety-backend:dev-0123456789ab'
  is_tickety_dev_image_ref 'localhost:32000/tickety-frontend:dev-abcdef012345'
  ! is_tickety_dev_image_ref 'localhost:32000/other:dev-0123456789ab'
  python3 "$ROOT_DIR/deploy/dev-microk8s/prune-registry.py" --self-test
  echo "Remote dev release self-test passed."
  exit 0
fi

(($# == 3)) || die "usage: remote-release.sh FULL_SHA SHORT_SHA BUILD_TIME"
readonly FULL_SHA=$1 SHORT_SHA=$2 BUILD_TIME=$3
[[ $FULL_SHA =~ ^[0-9a-f]{40}$ ]] || die "invalid full Git SHA"
[[ $SHORT_SHA =~ ^[0-9a-f]{12}$ && $FULL_SHA == "$SHORT_SHA"* ]] || die "invalid short Git SHA"
[[ $BUILD_TIME =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] || die "invalid build time"
[[ $(id -u) == 0 ]] || die "release must run through sudo"
[[ $(<"$ROOT_DIR/SOURCE_SHA") == "$FULL_SHA" ]] || die "release source marker differs from requested SHA"

readonly BACKEND_IMAGE=$REGISTRY/tickety-backend:dev-$SHORT_SHA
readonly FRONTEND_IMAGE=$REGISTRY/tickety-frontend:dev-$SHORT_SHA
readonly BACKUP_JOB=tickety-backup-dev-$SHORT_SHA
readonly MIGRATION_JOB=tickety-migrate-dev-$SHORT_SHA
readonly BACKUP_FILE=tickety-before-$SHORT_SHA.dump

for required_command in curl dig docker microk8s python3 sed; do
  command -v "$required_command" >/dev/null 2>&1 || die "required command is missing: $required_command"
done
[[ $(uname -m) == x86_64 ]] || die "dev host must be x86_64"
microk8s status --wait-ready >/dev/null
"${KUBECTL[@]}" get namespace "$NAMESPACE" >/dev/null
"${KUBECTL[@]}" -n "$NAMESPACE" get secret tickety-secrets >/dev/null
"${KUBECTL[@]}" -n "$NAMESPACE" get statefulset postgres >/dev/null
"${KUBECTL[@]}" -n "$NAMESPACE" get service postgres backend-service frontend-service >/dev/null
for deployment in backend backend-worker frontend; do
  "${KUBECTL[@]}" -n "$NAMESPACE" get deployment "$deployment" >/dev/null
done
ingress_hosts=$("${KUBECTL[@]}" -n "$NAMESPACE" get ingress frontend-ingress -o jsonpath='{range .spec.rules[*]}{.host}{"\n"}{end}')
[[ $ingress_hosts == "$PUBLIC_HOST" ]] || die "existing ingress does not exclusively target $PUBLIC_HOST"
curl --fail --silent --show-error --max-time 10 http://127.0.0.1:32000/v2/ >/dev/null || die "local MicroK8s registry is unavailable"
# A successful release removes its local build copies after pushing. An
# interrupted verification can leave the immutable tags attached, so remove
# both tagged and dangling images carrying the Tickety-only dev label. Refuse
# to touch an image used by a running Docker container; MicroK8s pulls its own
# copy from the local registry and does not depend on Docker's image store.
cleanup_tickety_build_images
cleanup_tickety_completed_release_jobs_and_images
pruned_manifests=$(prune_tickety_registry_manifests \
  "$("${KUBECTL[@]}" -n "$NAMESPACE" get deployment backend \
    -o jsonpath='{.spec.template.spec.containers[?(@.name=="backend")].image}' | sed 's|.*:dev-||')")
available_kib=$(available_root_kib)
[[ $available_kib =~ ^[0-9]+$ ]] || die "could not measure root filesystem space"
if [[ $available_kib -lt 8388608 && $pruned_manifests -gt 0 ]]; then
  garbage_collect_tickety_registry
fi
wait_for_audited_build_space

# The dev host's resolver accepts DNS over UDP but not TCP. Large CNAME
# responses make glibc retry through CoreDNS over TCP, so CoreDNS must retry
# its upstream over UDP rather than mirroring the client transport.
coredns_corefile=$("${KUBECTL[@]}" -n kube-system get configmap coredns -o jsonpath='{.data.Corefile}')
rendered_corefile=$(printf '%s' "$coredns_corefile" | \
  python3 "$ROOT_DIR/deploy/dev-microk8s/ensure-coredns-prefer-udp.py")
if [[ $rendered_corefile != "$coredns_corefile" ]]; then
  coredns_patch=$(printf '%s' "$rendered_corefile" | python3 -c \
    'import json, sys; print(json.dumps({"data": {"Corefile": sys.stdin.read()}}))')
  "${KUBECTL[@]}" -n kube-system patch configmap coredns --type merge -p "$coredns_patch"
  "${KUBECTL[@]}" -n kube-system rollout restart deployment/coredns
  "${KUBECTL[@]}" -n kube-system rollout status deployment/coredns --timeout=5m
fi
printf '%s' "$("${KUBECTL[@]}" -n kube-system get configmap coredns -o jsonpath='{.data.Corefile}')" | \
  python3 "$ROOT_DIR/deploy/dev-microk8s/ensure-coredns-prefer-udp.py" --check

# glibc does not advertise EDNS0 by default. The host DNS proxy can return an
# oversized UDP answer but cannot complete CoreDNS's TCP retry, so both
# provider-calling workloads must advertise a large enough UDP response size.
dns_config_patch='{"spec":{"template":{"spec":{"dnsConfig":{"options":[{"name":"edns0"}]}}}}}'
for deployment in backend backend-worker; do
  "${KUBECTL[@]}" -n "$NAMESPACE" patch deployment "$deployment" \
    --type strategic -p "$dns_config_patch"
  "${KUBECTL[@]}" -n "$NAMESPACE" set env "deployment/$deployment" \
    DIRECTORY_PEOPLE_READ_ENABLED=true \
    DIRECTORY_PEOPLE_WRITE_ENABLED=true \
    REMOTE_AGENT_TEAM_ELIGIBLE=true
done

echo "Building immutable dev images for $FULL_SHA"
docker build --pull=false --target backend \
  --label "com.tickety.dev=true" \
  --build-arg "BUILD_SHA=$SHORT_SHA" --build-arg "BUILD_TIME=$BUILD_TIME" \
  --tag "$BACKEND_IMAGE" "$ROOT_DIR"
docker push "$BACKEND_IMAGE"
docker build --pull=false --target frontend \
  --label "com.tickety.dev=true" \
  --build-arg "BUILD_SHA=$SHORT_SHA" --build-arg "BUILD_TIME=$BUILD_TIME" \
  --tag "$FRONTEND_IMAGE" "$ROOT_DIR"
docker push "$FRONTEND_IMAGE"

temporary_dir=$(mktemp -d /tmp/tickety-dev-release.XXXXXX)
cleanup() { rm -rf -- "$temporary_dir"; }
trap cleanup EXIT
render() {
  local source=$1 destination=$2
  sed -e "s|@BACKEND_IMAGE@|$BACKEND_IMAGE|g" \
    -e "s|@BACKUP_JOB@|$BACKUP_JOB|g" -e "s|@BACKUP_FILE@|$BACKUP_FILE|g" \
    -e "s|@MIGRATION_JOB@|$MIGRATION_JOB|g" "$source" >"$destination"
  ! grep -Eq '@[A-Z_]+@' "$destination" || die "unrendered manifest placeholder in $destination"
}

"${KUBECTL[@]}" apply -f "$ROOT_DIR/deploy/dev-microk8s/backup-storage.yaml"
render "$ROOT_DIR/deploy/dev-microk8s/backup-job.yaml.tpl" "$temporary_dir/backup.yaml"
"${KUBECTL[@]}" -n "$NAMESPACE" delete job "$BACKUP_JOB" --ignore-not-found=true --wait=true
"${KUBECTL[@]}" apply -f "$temporary_dir/backup.yaml"
"${KUBECTL[@]}" -n "$NAMESPACE" wait --for=condition=complete "job/$BACKUP_JOB" --timeout=10m
[[ $("${KUBECTL[@]}" -n "$NAMESPACE" get job "$BACKUP_JOB" -o jsonpath='{.status.succeeded}') == 1 ]] || die "database backup did not complete"

render "$ROOT_DIR/deploy/dev-microk8s/migration-job.yaml.tpl" "$temporary_dir/migration.yaml"
"${KUBECTL[@]}" -n "$NAMESPACE" delete job "$MIGRATION_JOB" --ignore-not-found=true --wait=true
"${KUBECTL[@]}" apply -f "$temporary_dir/migration.yaml"
"${KUBECTL[@]}" -n "$NAMESPACE" wait --for=condition=complete "job/$MIGRATION_JOB" --timeout=10m
[[ $("${KUBECTL[@]}" -n "$NAMESPACE" get job "$MIGRATION_JOB" -o jsonpath='{.status.succeeded}') == 1 ]] || die "database migration did not complete"

{
  echo "backend=$("${KUBECTL[@]}" -n "$NAMESPACE" get deployment backend -o jsonpath='{.spec.template.spec.containers[?(@.name=="backend")].image}')"
  echo "worker=$("${KUBECTL[@]}" -n "$NAMESPACE" get deployment backend-worker -o jsonpath='{.spec.template.spec.containers[?(@.name=="worker")].image}')"
  echo "frontend=$("${KUBECTL[@]}" -n "$NAMESPACE" get deployment frontend -o jsonpath='{.spec.template.spec.containers[?(@.name=="frontend")].image}')"
} >"$ROOT_DIR/PREVIOUS_IMAGES"

"${KUBECTL[@]}" -n "$NAMESPACE" set image deployment/backend "wait-for-postgres=$BACKEND_IMAGE" "backend=$BACKEND_IMAGE"
"${KUBECTL[@]}" -n "$NAMESPACE" set image deployment/backend-worker "wait-for-postgres=$BACKEND_IMAGE" "worker=$BACKEND_IMAGE"
"${KUBECTL[@]}" -n "$NAMESPACE" set image deployment/frontend "frontend=$FRONTEND_IMAGE"
for deployment in backend backend-worker frontend; do
  "${KUBECTL[@]}" -n "$NAMESPACE" scale "deployment/$deployment" --replicas=1
done
for deployment in backend backend-worker frontend; do
  "${KUBECTL[@]}" -n "$NAMESPACE" annotate deployment "$deployment" \
    tickety.dev/source-sha="$FULL_SHA" tickety.dev/build-time="$BUILD_TIME" --overwrite
  "${KUBECTL[@]}" -n "$NAMESPACE" rollout status "deployment/$deployment" --timeout=10m
done

"$ROOT_DIR/deploy/dev-microk8s/verify.sh" "$FULL_SHA" "$SHORT_SHA"
cleanup_tickety_completed_release_jobs_and_images
pruned_manifests=$(prune_tickety_registry_manifests "$SHORT_SHA")
if [[ $pruned_manifests -gt 0 ]]; then
  garbage_collect_tickety_registry
fi
cleanup_tickety_build_images
echo "Dev release completed: source=$FULL_SHA backup=$BACKUP_JOB migration=$MIGRATION_JOB"
