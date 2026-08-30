#!/usr/bin/env python3
"""Select a ready container for the expected immutable deployment image."""

from __future__ import annotations

import argparse
import json
import re
import sys


CONTAINER_ID = re.compile(r"^(?:containerd://)?([0-9a-f]{64})$")


def select_container_id(payload: dict, *, image: str, container: str) -> str:
    candidates: list[tuple[str, str]] = []
    for pod in payload.get("items", []):
        metadata = pod.get("metadata", {})
        spec = pod.get("spec", {})
        status = pod.get("status", {})
        if metadata.get("deletionTimestamp") or status.get("phase") != "Running":
            continue
        declared = {
            item.get("name"): item.get("image") for item in spec.get("containers", [])
        }
        if declared.get(container) != image:
            continue
        for item in status.get("containerStatuses", []):
            if (
                item.get("name") != container
                or not item.get("ready")
                or not item.get("state", {}).get("running")
            ):
                continue
            match = CONTAINER_ID.fullmatch(str(item.get("containerID") or ""))
            if match:
                candidates.append(
                    (str(metadata.get("creationTimestamp") or ""), match.group(1))
                )
    if not candidates:
        raise ValueError("no ready container matches the expected immutable image")
    return max(candidates)[1]


def self_test() -> None:
    old_id = "a" * 64
    current_id = "b" * 64
    fixture = {
        "items": [
            {
                "metadata": {
                    "creationTimestamp": "2026-01-01T00:00:00Z",
                    "deletionTimestamp": "2026-01-01T00:02:00Z",
                },
                "spec": {"containers": [{"name": "backend", "image": "old"}]},
                "status": {
                    "phase": "Running",
                    "containerStatuses": [
                        {
                            "name": "backend",
                            "ready": True,
                            "state": {"running": {}},
                            "containerID": f"containerd://{old_id}",
                        }
                    ],
                },
            },
            {
                "metadata": {"creationTimestamp": "2026-01-01T00:01:00Z"},
                "spec": {
                    "containers": [{"name": "backend", "image": "expected"}]
                },
                "status": {
                    "phase": "Running",
                    "containerStatuses": [
                        {
                            "name": "backend",
                            "ready": True,
                            "state": {"running": {"startedAt": "now"}},
                            "containerID": f"containerd://{current_id}",
                        }
                    ],
                },
            },
        ]
    }
    assert select_container_id(
        fixture, image="expected", container="backend"
    ) == current_id
    print("Ready immutable container selector self-test passed.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image")
    parser.add_argument("--container")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.image or not args.container:
        parser.error("--image and --container are required")
    print(
        select_container_id(
            json.load(sys.stdin), image=args.image, container=args.container
        )
    )


if __name__ == "__main__":
    main()
