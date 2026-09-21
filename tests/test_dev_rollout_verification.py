import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "deploy/dev-microk8s/verify-rollout.py"
SPEC = importlib.util.spec_from_file_location("verify_dev_rollout", MODULE_PATH)
rollout = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rollout)


class DevRolloutVerificationTests(unittest.TestCase):
    def setUp(self):
        self.deployment = {
            "metadata": {"name": "backend", "generation": 7},
            "spec": {"replicas": 1},
            "status": {
                "observedGeneration": 7,
                "replicas": 1,
                "updatedReplicas": 1,
                "readyReplicas": 1,
                "availableReplicas": 1,
            },
        }

    def test_completed_rollout_passes(self):
        rollout.verify_rollout(self.deployment)

    def test_old_available_replica_cannot_prove_new_release(self):
        self.deployment["status"]["observedGeneration"] = 6
        # The previous desired == available gate accepts this stale snapshot.
        self.assertEqual(self.deployment["spec"]["replicas"],
                         self.deployment["status"]["availableReplicas"])
        with self.assertRaisesRegex(ValueError, "not observed"):
            rollout.verify_rollout(self.deployment)

    def test_incomplete_or_missing_replica_counts_fail(self):
        for field in ("replicas", "updatedReplicas", "readyReplicas", "availableReplicas"):
            for value in (0, 2, None, True, "1"):
                with self.subTest(field=field, value=value):
                    self.deployment["status"][field] = value
                    with self.assertRaisesRegex(ValueError, field):
                        rollout.verify_rollout(self.deployment)
                    self.deployment["status"][field] = 1
            with self.subTest(field=field, missing=True):
                del self.deployment["status"][field]
                with self.assertRaisesRegex(ValueError, field):
                    rollout.verify_rollout(self.deployment)
                self.deployment["status"][field] = 1

    def test_scaled_down_deployment_cannot_pass(self):
        self.deployment["spec"]["replicas"] = 0
        for field in ("replicas", "updatedReplicas", "readyReplicas", "availableReplicas"):
            self.deployment["status"][field] = 0
        with self.assertRaisesRegex(ValueError, "at least one"):
            rollout.verify_rollout(self.deployment)

    def test_missing_generation_fails(self):
        del self.deployment["status"]["observedGeneration"]
        with self.assertRaisesRegex(ValueError, "not observed"):
            rollout.verify_rollout(self.deployment)

    def test_terminating_deployment_fails(self):
        self.deployment["metadata"]["deletionTimestamp"] = "2026-09-21T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "terminating"):
            rollout.verify_rollout(self.deployment)

    def test_controller_failures_are_rejected(self):
        for kind, status in (("Progressing", "False"), ("ReplicaFailure", "True")):
            with self.subTest(kind=kind):
                self.deployment["status"]["conditions"] = [{"type": kind, "status": status}]
                with self.assertRaisesRegex(ValueError, "rollout failure"):
                    rollout.verify_rollout(self.deployment)


if __name__ == "__main__":
    unittest.main()
