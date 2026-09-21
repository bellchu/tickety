#!/usr/bin/env python3
"""Reject stale or incomplete Kubernetes Deployment rollout evidence."""

from __future__ import annotations

import json
import sys


def verify_rollout(deployment: dict) -> None:
    metadata = deployment.get("metadata", {})
    spec = deployment.get("spec", {})
    status = deployment.get("status", {})
    name = metadata.get("name", "deployment")

    def reject(reason: str) -> None:
        raise ValueError(f"{name}: {reason}")

    if metadata.get("deletionTimestamp"):
        reject("deployment is terminating")
    desired = spec.get("replicas")
    if type(desired) is not int or desired < 1:
        reject("at least one desired replica is required")
    generation = metadata.get("generation")
    observed = status.get("observedGeneration")
    if (
        type(generation) is not int
        or generation < 1
        or type(observed) is not int
        or observed < generation
    ):
        reject("controller has not observed the current deployment generation")
    for field in ("replicas", "updatedReplicas", "readyReplicas", "availableReplicas"):
        if type(status.get(field)) is not int or status[field] != desired:
            reject(f"{field} does not match the desired replica count")
    for condition in status.get("conditions", []):
        if (
            condition.get("type") == "Progressing"
            and condition.get("status") == "False"
        ) or (
            condition.get("type") == "ReplicaFailure"
            and condition.get("status") == "True"
        ):
            reject("controller reports a rollout failure")


def main() -> None:
    try:
        verify_rollout(json.load(sys.stdin))
    except (ValueError, TypeError, AttributeError) as exc:
        raise SystemExit(f"Dev rollout verification failed: {exc}") from None


if __name__ == "__main__":
    main()
