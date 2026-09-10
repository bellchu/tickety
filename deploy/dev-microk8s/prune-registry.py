#!/usr/bin/env python3
"""Delete stale Tickety manifests from the isolated MicroK8s registry."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


REGISTRY_URL = "http://127.0.0.1:32000"
ACTIVE_REPOSITORIES = ("tickety-backend", "tickety-frontend")
RETIRED_REPOSITORIES = (
    "tickety-build-cache",
    "tickety-cache",
    "tickety-cache/frontend",
    "tickety-frontend-arm64",
)
ALLOWED_REPOSITORIES = frozenset((*ACTIVE_REPOSITORIES, *RETIRED_REPOSITORIES))
MANIFEST_ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
    )
)


class RegistryPruneError(RuntimeError):
    pass


@dataclass(frozen=True)
class ManifestDeletion:
    repository: str
    digest: str


def select_deletions(
    tags_by_repository: Mapping[str, list[str]],
    digests_by_reference: Mapping[tuple[str, str], str],
    keep_tags: Mapping[str, str],
) -> list[ManifestDeletion]:
    protected: dict[str, str] = {}
    for repository, tag in keep_tags.items():
        try:
            protected[repository] = digests_by_reference[(repository, tag)]
        except KeyError as exc:
            raise RegistryPruneError(
                f"required current registry tag is missing: {repository}:{tag}"
            ) from exc

    deletions: set[ManifestDeletion] = set()
    for repository, tags in tags_by_repository.items():
        if repository not in ALLOWED_REPOSITORIES:
            raise RegistryPruneError(f"repository is outside the Tickety allowlist: {repository}")
        keep_tag = keep_tags.get(repository)
        protected_digest = protected.get(repository)
        for tag in tags:
            if tag == keep_tag:
                continue
            digest = digests_by_reference[(repository, tag)]
            if protected_digest is not None and digest == protected_digest:
                raise RegistryPruneError(
                    f"stale tag shares the current manifest and cannot be deleted safely: "
                    f"{repository}:{tag}"
                )
            deletions.add(ManifestDeletion(repository, digest))
    return sorted(deletions, key=lambda item: (item.repository, item.digest))


class RegistryClient:
    def __init__(self, base_url: str) -> None:
        if base_url.rstrip("/") != REGISTRY_URL:
            raise RegistryPruneError(
                f"registry must be the audited local MicroK8s endpoint: {REGISTRY_URL}"
            )
        self.base_url = REGISTRY_URL

    def _request(self, path: str, *, method: str = "GET", headers: dict[str, str] | None = None):
        request = Request(f"{self.base_url}{path}", method=method, headers=headers or {})
        try:
            return urlopen(request, timeout=20)
        except HTTPError as exc:
            raise RegistryPruneError(
                f"registry {method} failed for {path}: HTTP {exc.code}"
            ) from exc

    def tags(self, repository: str) -> list[str]:
        path = f"/v2/{quote(repository, safe='/')}/tags/list"
        with self._request(path) as response:
            payload = json.load(response)
        tags = payload.get("tags") or []
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise RegistryPruneError(f"invalid tag inventory for {repository}")
        return tags

    def digest(self, repository: str, tag: str) -> str:
        path = f"/v2/{quote(repository, safe='/')}/manifests/{quote(tag, safe='')}"
        with self._request(path, method="HEAD", headers={"Accept": MANIFEST_ACCEPT}) as response:
            digest = response.headers.get("Docker-Content-Digest", "")
        if not digest.startswith("sha256:") or len(digest) != 71:
            raise RegistryPruneError(f"invalid manifest digest for {repository}:{tag}")
        return digest

    def delete(self, deletion: ManifestDeletion) -> None:
        path = (
            f"/v2/{quote(deletion.repository, safe='/')}/manifests/"
            f"{quote(deletion.digest, safe=':')}"
        )
        with self._request(path, method="DELETE"):
            return


def run_self_test() -> None:
    tags = {
        "tickety-backend": ["dev-current", "dev-old", "dev-old-alias"],
        "tickety-frontend": ["dev-current", "dev-old"],
        "tickety-cache": ["legacy"],
    }
    digests = {
        ("tickety-backend", "dev-current"): "sha256:" + "a" * 64,
        ("tickety-backend", "dev-old"): "sha256:" + "b" * 64,
        ("tickety-backend", "dev-old-alias"): "sha256:" + "b" * 64,
        ("tickety-frontend", "dev-current"): "sha256:" + "c" * 64,
        ("tickety-frontend", "dev-old"): "sha256:" + "d" * 64,
        ("tickety-cache", "legacy"): "sha256:" + "e" * 64,
    }
    keep = {
        "tickety-backend": "dev-current",
        "tickety-frontend": "dev-current",
    }
    selected = select_deletions(tags, digests, keep)
    assert selected == [
        ManifestDeletion("tickety-backend", "sha256:" + "b" * 64),
        ManifestDeletion("tickety-cache", "sha256:" + "e" * 64),
        ManifestDeletion("tickety-frontend", "sha256:" + "d" * 64),
    ]

    conflicting = dict(digests)
    conflicting[("tickety-backend", "dev-old")] = conflicting[
        ("tickety-backend", "dev-current")
    ]
    try:
        select_deletions(tags, conflicting, keep)
    except RegistryPruneError as exc:
        assert "shares the current manifest" in str(exc)
    else:
        raise AssertionError("a stale alias of the current manifest was not rejected")
    print("Tickety registry retention self-test passed.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", default=REGISTRY_URL)
    parser.add_argument("--keep-backend")
    parser.add_argument("--keep-frontend")
    parser.add_argument("--delete", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        run_self_test()
        return 0
    if not args.keep_backend or not args.keep_frontend:
        parser.error("--keep-backend and --keep-frontend are required")

    keep_tags = {
        "tickety-backend": args.keep_backend,
        "tickety-frontend": args.keep_frontend,
    }
    client = RegistryClient(args.registry)
    tags_by_repository = {
        repository: client.tags(repository) for repository in ALLOWED_REPOSITORIES
    }
    digests_by_reference = {
        (repository, tag): client.digest(repository, tag)
        for repository, tags in tags_by_repository.items()
        for tag in tags
    }
    deletions = select_deletions(tags_by_repository, digests_by_reference, keep_tags)
    if not args.delete:
        print(len(deletions))
        return 0
    for deletion in deletions:
        client.delete(deletion)

    expected = {
        "tickety-backend": {args.keep_backend},
        "tickety-frontend": {args.keep_frontend},
        **{repository: set() for repository in RETIRED_REPOSITORIES},
    }
    for repository, expected_tags in expected.items():
        remaining = set(client.tags(repository))
        if remaining != expected_tags:
            raise RegistryPruneError(
                f"registry retention verification failed for {repository}: "
                f"{sorted(remaining)}"
            )
    print(len(deletions))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RegistryPruneError as exc:
        print(f"Registry prune failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
