#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
DEV_DIR=$ROOT_DIR/deploy/dev-microk8s

bash -n "$DEV_DIR/install-release.sh" "$DEV_DIR/remote-release.sh" "$DEV_DIR/verify.sh" \
  "$ROOT_DIR/scripts/deploy-dev-microk8s.sh" "$ROOT_DIR/scripts/validate-dev-deployment.sh"
python3 "$DEV_DIR/ensure-coredns-prefer-udp.py" --self-test
python3 "$DEV_DIR/select-ready-container.py" --self-test
python3 "$DEV_DIR/prune-registry.py" --self-test
"$ROOT_DIR/scripts/deploy-dev-microk8s.sh" --self-test

grep -Fq 'TICKETY_DEV_PUBLIC_HOST' "$DEV_DIR/remote-release.sh"
grep -Fq 'TICKETY_DEV_PUBLIC_HOST' "$DEV_DIR/verify.sh"
grep -Fq 'TICKETY_DEV_SSH_ALIAS' "$ROOT_DIR/scripts/deploy-dev-microk8s.sh"
grep -Fq 'scp -O' "$ROOT_DIR/scripts/deploy-dev-microk8s.sh"
grep -Fq '[[ $branch == dev ]]' "$ROOT_DIR/scripts/deploy-dev-microk8s.sh"
grep -Fq 'local dev must exactly match origin/dev' "$ROOT_DIR/scripts/deploy-dev-microk8s.sh"
grep -Fq 'name: tickety-secrets' "$DEV_DIR/backup-job.yaml.tpl"
grep -Fq 'name: tickety-secrets' "$DEV_DIR/migration-job.yaml.tpl"
grep -Fq 'pg_restore --list' "$DEV_DIR/backup-job.yaml.tpl"
grep -Fq 'alembic", "upgrade", "head' "$DEV_DIR/migration-job.yaml.tpl"
grep -Fq 'ensure-coredns-prefer-udp.py' "$DEV_DIR/remote-release.sh"
grep -Fq 'dnsConfig' "$DEV_DIR/remote-release.sh"
grep -Fq '"edns0"' "$DEV_DIR/remote-release.sh"
grep -Fq 'DIRECTORY_PEOPLE_READ_ENABLED=true' "$DEV_DIR/remote-release.sh"
grep -Fq 'DIRECTORY_PEOPLE_WRITE_ENABLED=true' "$DEV_DIR/remote-release.sh"
grep -Fq 'REMOTE_AGENT_TEAM_ELIGIBLE=true' "$DEV_DIR/remote-release.sh"
grep -Fq 'expected_directory_env' "$DEV_DIR/verify.sh"
grep -Fq -- '--label "com.tickety.dev=true"' "$DEV_DIR/remote-release.sh"
grep -Fq 'cleanup_tickety_build_images' "$DEV_DIR/remote-release.sh"
grep -Fq 'cleanup_tickety_completed_release_jobs_and_images' "$DEV_DIR/remote-release.sh"
grep -Fq 'is_tickety_dev_job_name' "$DEV_DIR/remote-release.sh"
grep -Fq 'is_tickety_dev_image_ref' "$DEV_DIR/remote-release.sh"
grep -Fq 'microk8s ctr images rm' "$DEV_DIR/remote-release.sh"
grep -Fq 'wait_for_audited_build_space' "$DEV_DIR/remote-release.sh"
grep -Fq 'prune_tickety_registry_manifests' "$DEV_DIR/remote-release.sh"
grep -Fq 'garbage_collect_tickety_registry' "$DEV_DIR/remote-release.sh"
grep -Fq 'registry-claim' "$DEV_DIR/remote-release.sh"
grep -Fq -- '--delete-untagged' "$DEV_DIR/remote-release.sh"
grep -Fq 'RETIRED_REPOSITORIES' "$DEV_DIR/prune-registry.py"
grep -Fq 'shares the current manifest' "$DEV_DIR/prune-registry.py"
grep -Fq 'scale "deployment/$deployment" --replicas=1' "$DEV_DIR/remote-release.sh"
release_cleanup_count=$(grep -cFx 'cleanup_tickety_completed_release_jobs_and_images' \
  "$DEV_DIR/remote-release.sh")
pre_release_cleanup_line=$(grep -nFx 'cleanup_tickety_completed_release_jobs_and_images' \
  "$DEV_DIR/remote-release.sh" | head -n 1 | cut -d: -f1)
post_release_cleanup_line=$(grep -nFx 'cleanup_tickety_completed_release_jobs_and_images' \
  "$DEV_DIR/remote-release.sh" | tail -n 1 | cut -d: -f1)
space_gate_line=$(grep -nF 'wait_for_audited_build_space' \
  "$DEV_DIR/remote-release.sh" | tail -n 1 | cut -d: -f1)
release_verify_line=$(grep -nF 'verify.sh" "$FULL_SHA" "$SHORT_SHA"' \
  "$DEV_DIR/remote-release.sh" | cut -d: -f1)
[[ $release_cleanup_count == 2 \
  && $pre_release_cleanup_line =~ ^[0-9]+$ \
  && $post_release_cleanup_line =~ ^[0-9]+$ \
  && $space_gate_line =~ ^[0-9]+$ \
  && $release_verify_line =~ ^[0-9]+$ \
  && $pre_release_cleanup_line -lt $space_gate_line \
  && $post_release_cleanup_line -gt $release_verify_line ]]
grep -Fq 'normalize_docker_image_id' "$DEV_DIR/remote-release.sh"
grep -Fq 'sha256:$test_image_id' "$DEV_DIR/remote-release.sh"
grep -Fq 'docker image ls --all --quiet --no-trunc' "$DEV_DIR/remote-release.sh"
grep -Fq 'docker image rm --no-prune "$image_id"' "$DEV_DIR/remote-release.sh"
grep -Fq 'docker ps --quiet --filter "ancestor=$image_id"' "$DEV_DIR/remote-release.sh"
grep -Fq "docker image inspect --format '{{.Parent}}'" "$DEV_DIR/remote-release.sh"
grep -Fq "docker image inspect --format '{{json .RepoTags}}'" "$DEV_DIR/remote-release.sh"
grep -Fq 'docker image prune --force --filter "label=com.tickety.dev=true"' "$DEV_DIR/remote-release.sh"
grep -Fq 'label=com.tickety.build-stage=frontend' "$DEV_DIR/remote-release.sh"
grep -Fq 'LABEL com.tickety.build-stage="frontend"' "$ROOT_DIR/Dockerfile"
grep -Fq 'dig +tcp' "$DEV_DIR/verify.sh"
grep -Fq 'microk8s ctr tasks exec' "$DEV_DIR/verify.sh"
grep -Fq 'select-ready-container.py' "$DEV_DIR/verify.sh"
grep -Fq 'socket.getaddrinfo' "$DEV_DIR/verify.sh"
if "$ROOT_DIR/deploy.sh" dev >/dev/null 2>&1; then
  echo "Production deploy.sh unexpectedly accepted the dev path." >&2
  exit 1
fi
echo "Dev deployment validation passed."
