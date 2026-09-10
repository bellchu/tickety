#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SSH_OPTIONS=(-o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=yes -o ClearAllForwardings=yes)

die() { echo "Dev deployment rejected: $*" >&2; exit 1; }

if [[ ${1:-} == --self-test ]]; then
  export TICKETY_DEV_NAMESPACE=tickety
  export TICKETY_DEV_PUBLIC_HOST=dev.tickety.example
  export TICKETY_DEV_REGISTRY=localhost:32000
  "$ROOT_DIR/deploy/dev-microk8s/install-release.sh" --self-test
  "$ROOT_DIR/deploy/dev-microk8s/remote-release.sh" --self-test
  echo "Local dev deployment self-test passed."
  exit 0
fi
(($# == 0)) || die "no arguments are accepted; the release is always the pushed dev commit"

: "${TICKETY_DEV_SSH_ALIAS:?set TICKETY_DEV_SSH_ALIAS}"
: "${TICKETY_DEV_SSH_HOST:?set TICKETY_DEV_SSH_HOST}"
: "${TICKETY_DEV_SSH_USER:?set TICKETY_DEV_SSH_USER}"
: "${TICKETY_DEV_PUBLIC_HOST:?set TICKETY_DEV_PUBLIC_HOST}"
readonly SSH_ALIAS=$TICKETY_DEV_SSH_ALIAS EXPECTED_HOST=$TICKETY_DEV_SSH_HOST
readonly EXPECTED_USER=$TICKETY_DEV_SSH_USER
readonly DEV_NAMESPACE=${TICKETY_DEV_NAMESPACE:-tickety}
readonly DEV_REGISTRY=${TICKETY_DEV_REGISTRY:-localhost:32000}

for required_command in git scp sha256sum ssh; do
  command -v "$required_command" >/dev/null 2>&1 || die "required command is missing: $required_command"
done
effective_config=$(ssh -G "$SSH_ALIAS" 2>/dev/null)
effective_host=$(awk '$1 == "hostname" {print $2; exit}' <<<"$effective_config")
effective_user=$(awk '$1 == "user" {print $2; exit}' <<<"$effective_config")
[[ $effective_host == "$EXPECTED_HOST" && $effective_user == "$EXPECTED_USER" ]] || die "SSH alias must resolve to $EXPECTED_USER@$EXPECTED_HOST"

branch=$(git -C "$ROOT_DIR" branch --show-current)
[[ $branch == dev ]] || die "current branch must be dev"
git -C "$ROOT_DIR" fetch origin dev
full_sha=$(git -C "$ROOT_DIR" rev-parse dev)
remote_sha=$(git -C "$ROOT_DIR" rev-parse origin/dev)
[[ $full_sha == "$remote_sha" ]] || die "local dev must exactly match origin/dev"
short_sha=$(git -C "$ROOT_DIR" rev-parse --short=12 "$full_sha")
build_time=$(date -u +%Y-%m-%dT%H:%M:%SZ)

temporary_dir=$(mktemp -d /tmp/tickety-dev-deploy.XXXXXX)
cleanup() { rm -rf -- "$temporary_dir"; }
trap cleanup EXIT
archive=$temporary_dir/tickety-dev-${full_sha}.tar
git -C "$ROOT_DIR" archive --format=tar --output="$archive" "$full_sha"
archive_sha=$(sha256sum "$archive" | awk '{print $1}')

remote_archive=/tmp/tickety-dev-${full_sha}.tar
remote_installer=/tmp/tickety-dev-install-${short_sha}.sh
# The development host may expose the audited SSH command channel without an
# SFTP subsystem. Force the legacy SCP protocol over that same SSH transport.
scp -O "${SSH_OPTIONS[@]}" "$archive" "$SSH_ALIAS:$remote_archive"
scp -O "${SSH_OPTIONS[@]}" "$ROOT_DIR/deploy/dev-microk8s/install-release.sh" "$SSH_ALIAS:$remote_installer"
release_dir=$(ssh "${SSH_OPTIONS[@]}" "$SSH_ALIAS" sudo -n bash "$remote_installer" "$full_sha" "$archive_sha" "$remote_archive")
ssh "${SSH_OPTIONS[@]}" "$SSH_ALIAS" sudo -n rm -f -- "$remote_installer"
[[ $release_dir == /srv/tickety-dev/releases/$full_sha ]] || die "remote installer returned an unexpected release path"

ssh "${SSH_OPTIONS[@]}" "$SSH_ALIAS" sudo -n \
  env TICKETY_DEV_NAMESPACE="$DEV_NAMESPACE" \
  TICKETY_DEV_PUBLIC_HOST="$TICKETY_DEV_PUBLIC_HOST" \
  TICKETY_DEV_REGISTRY="$DEV_REGISTRY" \
  "$release_dir/deploy/dev-microk8s/remote-release.sh" "$full_sha" "$short_sha" "$build_time"
echo "Dev deployment verified at https://$TICKETY_DEV_PUBLIC_HOST (source $full_sha)."
