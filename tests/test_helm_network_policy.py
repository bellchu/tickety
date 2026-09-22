"""Static guardrails for the chart's application-network isolation."""
from pathlib import Path
import unittest


class HelmNetworkPolicyTests(unittest.TestCase):
    def test_backend_ingress_is_limited_to_the_frontend_proxy(self):
        root = Path(__file__).resolve().parents[1]
        template = (
            root / "deploy/helm/tickety/templates/networkpolicy.yaml"
        ).read_text()

        start = template.index('name: {{ include "tickety.fullname" . }}-backend-ingress')
        end = template.index('name: {{ include "tickety.fullname" . }}-frontend-egress')
        backend_ingress = template[start:end]

        self.assertIn("policyTypes: [Ingress]", backend_ingress)
        self.assertIn('component" "backend")', backend_ingress)
        self.assertIn('component" "frontend")', backend_ingress)
        self.assertIn("port: 8000", backend_ingress)
        self.assertNotIn("namespaceSelector", backend_ingress)
        self.assertNotIn("ipBlock", backend_ingress)

    def test_frontend_egress_is_limited_to_dns_and_the_backend(self):
        root = Path(__file__).resolve().parents[1]
        template = (
            root / "deploy/helm/tickety/templates/networkpolicy.yaml"
        ).read_text()

        start = template.index('name: {{ include "tickety.fullname" . }}-frontend-egress')
        end = template.index('name: {{ include "tickety.fullname" . }}-backend-egress')
        frontend_egress = template[start:end]

        self.assertIn("policyTypes: [Egress]", frontend_egress)
        self.assertIn('component" "frontend")', frontend_egress)
        self.assertIn('component" "backend")', frontend_egress)
        self.assertIn("k8s-app: kube-dns", frontend_egress)
        self.assertIn("port: 53", frontend_egress)
        self.assertIn("port: 8000", frontend_egress)
        self.assertNotIn("ipBlock", frontend_egress)
        self.assertNotIn("additionalEgress", frontend_egress)

    def test_postgresql_is_egress_isolated_and_has_a_restricted_runtime_context(self):
        root = Path(__file__).resolve().parents[1]
        network_policy = (
            root / "deploy/helm/tickety/templates/networkpolicy.yaml"
        ).read_text()
        postgresql = (
            root / "deploy/helm/tickety/templates/postgresql.yaml"
        ).read_text()

        start = network_policy.index('name: {{ include "tickety.fullname" . }}-postgresql-egress')
        postgresql_egress = network_policy[start:]
        self.assertIn("policyTypes: [Egress]", postgresql_egress)
        self.assertIn('component" "postgresql")', postgresql_egress)
        self.assertIn("egress: []", postgresql_egress)

        self.assertIn("runAsNonRoot: true", postgresql)
        self.assertIn("runAsUser: 999", postgresql)
        self.assertIn("runAsGroup: 999", postgresql)
        self.assertIn("fsGroup: 999", postgresql)
        self.assertIn("fsGroupChangePolicy: OnRootMismatch", postgresql)
        self.assertIn("allowPrivilegeEscalation: false", postgresql)
        self.assertIn('drop: ["ALL"]', postgresql)
        self.assertNotIn("readOnlyRootFilesystem", postgresql)

    def test_outbox_configuration_does_not_require_the_optional_worker(self):
        root = Path(__file__).resolve().parents[1]
        configmap = (root / "deploy/helm/tickety/templates/configmap.yaml").read_text()
        values = (root / "deploy/helm/tickety/values.yaml").read_text()

        self.assertNotIn("worker.enabled must remain true", configmap)
        self.assertIn("NOTIFICATION_OUTBOX_PRUNE_INTERVAL_SECONDS", configmap)
        self.assertIn("notificationOutboxPruneIntervalSeconds: 300", values)

    def test_backup_egress_is_limited_to_dns_and_bundled_postgresql(self):
        root = Path(__file__).resolve().parents[1]
        template = (
            root / "deploy/helm/tickety/templates/networkpolicy.yaml"
        ).read_text()

        start = template.index('name: {{ include "tickety.fullname" . }}-backup-egress')
        end = template.index('name: {{ include "tickety.fullname" . }}-postgresql-ingress')
        backup_egress = template[start:end]
        self.assertIn('component" "backup")', backup_egress)
        self.assertIn("policyTypes: [Egress]", backup_egress)
        self.assertIn("k8s-app: kube-dns", backup_egress)
        self.assertIn("port: 53", backup_egress)
        self.assertIn('component" "postgresql")', backup_egress)
        self.assertIn("port: 5432", backup_egress)
        self.assertNotIn("additionalEgress", backup_egress)
        self.assertNotIn("ipBlock", backup_egress)


if __name__ == "__main__":
    unittest.main()
