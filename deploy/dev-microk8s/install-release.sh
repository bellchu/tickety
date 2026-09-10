#!/usr/bin/env bash
set -euo pipefail

readonly RELEASE_ROOT=/srv/tickety-dev

die() { echo "Dev release installation failed: $*" >&2; exit 1; }

if [[ ${1:-} == --self-test ]]; then
  [[ $RELEASE_ROOT == /srv/tickety-dev ]]
  echo "Dev release installer self-test passed."
  exit 0
fi

[[ $(id -u) == 0 ]] || die "installer must run through sudo"
(($# == 3)) || die "usage: install-release.sh FULL_SHA ARCHIVE_SHA256 ARCHIVE_PATH"
readonly FULL_SHA=$1 ARCHIVE_SHA256=$2 SOURCE_ARCHIVE=$3
[[ $FULL_SHA =~ ^[0-9a-f]{40}$ ]] || die "invalid Git SHA"
[[ $ARCHIVE_SHA256 =~ ^[0-9a-f]{64}$ ]] || die "invalid archive SHA-256"
[[ $SOURCE_ARCHIVE == /tmp/tickety-dev-${FULL_SHA}.tar ]] || die "unexpected archive path"
[[ -f $SOURCE_ARCHIVE && ! -L $SOURCE_ARCHIVE ]] || die "source archive is missing or unsafe"

actual_archive_sha=$(sha256sum "$SOURCE_ARCHIVE" | awk '{print $1}')
[[ $actual_archive_sha == "$ARCHIVE_SHA256" ]] || die "uploaded archive digest mismatch"

install -d -m 0750 "$RELEASE_ROOT" "$RELEASE_ROOT/incoming" "$RELEASE_ROOT/releases"
readonly RETAINED_ARCHIVE=$RELEASE_ROOT/incoming/${FULL_SHA}.tar
readonly RELEASE_DIR=$RELEASE_ROOT/releases/$FULL_SHA
if [[ -f $RETAINED_ARCHIVE ]]; then
  retained_sha=$(sha256sum "$RETAINED_ARCHIVE" | awk '{print $1}')
  [[ $retained_sha == "$ARCHIVE_SHA256" ]] || die "retained archive digest conflicts with this release"
else
  install -m 0640 "$SOURCE_ARCHIVE" "$RETAINED_ARCHIVE"
fi
rm -f -- "$SOURCE_ARCHIVE"

if [[ -d $RELEASE_DIR ]]; then
  [[ -f $RELEASE_DIR/SOURCE_ARCHIVE_SHA256 ]] || die "existing release lacks source evidence"
  [[ $(<"$RELEASE_DIR/SOURCE_ARCHIVE_SHA256") == "$ARCHIVE_SHA256" ]] || die "existing release digest differs"
else
  staging_dir=$(mktemp -d "$RELEASE_ROOT/releases/.${FULL_SHA}.XXXXXX")
  cleanup() { [[ -z ${staging_dir:-} || ! -d $staging_dir ]] || rm -rf -- "$staging_dir"; }
  trap cleanup EXIT
  tar -xf "$RETAINED_ARCHIVE" -C "$staging_dir"
  [[ -x $staging_dir/deploy/dev-microk8s/remote-release.sh ]] || die "archive lacks the dev release entrypoint"
  printf '%s\n' "$FULL_SHA" >"$staging_dir/SOURCE_SHA"
  printf '%s\n' "$ARCHIVE_SHA256" >"$staging_dir/SOURCE_ARCHIVE_SHA256"
  mv "$staging_dir" "$RELEASE_DIR"
  staging_dir=""
  trap - EXIT
fi

echo "$RELEASE_DIR"
