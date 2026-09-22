"""Static regression guards for release-safety deployment invariants."""
import json
import io
from pathlib import Path
import runpy
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

from app.backend import settings


class DeploymentHardeningTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]

    def test_dev_backup_pod_is_labeled_as_backup(self):
        template = (
            self.root / "deploy/dev-microk8s/backup-job.yaml.tpl"
        ).read_text()

        self.assertEqual(template.count("app.kubernetes.io/component: backup"), 2)
        self.assertNotIn("app.kubernetes.io/component: migration", template)

    def test_chart_created_backup_pvc_is_retained_on_release_removal(self):
        template = (
            self.root / "deploy/helm/tickety/templates/backup.yaml"
        ).read_text()
        chart_readme = (self.root / "deploy/helm/tickety/README.md").read_text()
        deployment_docs = (self.root / "docs/deployment.md").read_text()

        managed_claim = template[
            template.index("kind: PersistentVolumeClaim"):
            template.index("---", template.index("kind: PersistentVolumeClaim"))
        ]
        self.assertIn('"helm.sh/resource-policy": keep', managed_claim)
        self.assertIn("chart-created backup PVC", chart_readme)
        self.assertIn("retains it if the release is uninstalled", chart_readme)
        self.assertIn("chart-created backup PVC", deployment_docs)
        self.assertIn("Helm retains both the StatefulSet volume", deployment_docs)

    def test_postgresql_default_is_version_pinned_and_schema_rejects_floating_tags(self):
        values = (self.root / "deploy/helm/tickety/values.yaml").read_text()
        schema = json.loads(
            (self.root / "deploy/helm/tickety/values.schema.json").read_text()
        )

        self.assertIn("tag: 0.8.6-pg16", values)
        self.assertNotIn("tag: pg16", values)
        self.assertEqual(
            schema["properties"]["postgresql"]["properties"]["image"]["$ref"],
            "#/definitions/postgresqlImage",
        )
        self.assertEqual(
            schema["properties"]["frontend"]["properties"]["image"]["$ref"],
            "#/definitions/image",
        )
        self.assertEqual(
            schema["definitions"]["postgresqlImage"]["properties"]["tag"]["not"]["pattern"],
            "^(latest|pg[0-9]+)$",
        )

    def test_application_images_reject_latest_and_production_baseline_requires_replacement(self):
        values = (self.root / "deploy/helm/tickety/values.yaml").read_text()
        production_values = (
            self.root / "deploy/examples/production-values.yaml"
        ).read_text()
        schema = json.loads(
            (self.root / "deploy/helm/tickety/values.schema.json").read_text()
        )

        self.assertEqual(values.count("tag: dev"), 2)
        self.assertEqual(
            schema["definitions"]["image"]["properties"]["tag"]["not"]["pattern"],
            "^[lL][aA][tT][eE][sS][tT]$",
        )
        self.assertEqual(production_values.count("tag: REPLACE_WITH_GIT_SHA"), 2)
        self.assertIn("repository: registry.example.com/your-team/tickety/frontend", production_values)
        self.assertIn("repository: registry.example.com/your-team/tickety/backend", production_values)

    def test_session_storage_auto_is_safe_on_install_and_compatible_on_upgrade(self):
        values = (self.root / "deploy/helm/tickety/values.yaml").read_text()
        production_values = (
            self.root / "deploy/examples/production-values.yaml"
        ).read_text()
        template = (
            self.root / "deploy/helm/tickety/templates/configmap.yaml"
        ).read_text()
        schema = json.loads(
            (self.root / "deploy/helm/tickety/values.schema.json").read_text()
        )

        self.assertIn("sessionStorageMode: auto", values)
        self.assertIn("sessionStorageMode: auto", production_values)
        self.assertEqual(
            schema["properties"]["config"]["properties"]["sessionStorageMode"],
            {"enum": ["auto", "compat", "hashed"]},
        )
        self.assertIn('$sessionStorageMode = ternary "compat" "hashed" .Release.IsUpgrade', template)
        self.assertIn("SESSION_STORAGE_MODE: {{ $sessionStorageMode | quote }}", template)

    def test_deployer_retains_failed_upgrades_for_forward_recovery(self):
        deployer = (self.root / "deploy.sh").read_text()
        chart_readme = (self.root / "deploy/helm/tickety/README.md").read_text()

        self.assertIn(
            'helm status "$RELEASE" --namespace "$NAMESPACE" --output json',
            deployer,
        )
        self.assertIn('[[ $release_status == *"release: not found"* ]]', deployer)
        self.assertIn('release_operation_from_status "$release_status"', deployer)
        self.assertIn('\\"status\\"[[:space:]]*:[[:space:]]*\\"uninstalled\\"', deployer)
        self.assertIn('RELEASE_OPERATION=install', deployer)
        self.assertIn('if [[ $RELEASE_OPERATION == upgrade ]]; then', deployer)
        self.assertIn('upgrade "$RELEASE" "$CHART_DIR"', deployer)
        self.assertIn('    --reset-then-reuse-values\n', deployer)
        self.assertIn('require_safe_helm_upgrade_values_strategy', deployer)
        self.assertIn('Helm 3.14+ or Helm 4 is required', deployer)
        self.assertNotIn('    --atomic\n', deployer)
        self.assertIn('upgrade --install "$RELEASE" "$CHART_DIR"', deployer)
        self.assertIn("Do not use --atomic for a first install", deployer)
        self.assertIn("Database migrations are forward-only", deployer)
        self.assertIn("failed revisions are retained for forward recovery", deployer)
        self.assertIn("Deployment release-state self-test passed.", deployer)
        self.assertIn("It deliberately does not use `--atomic`.", chart_readme)
        self.assertIn("`--reset-then-reuse-values`", chart_readme)
        self.assertIn("Helm 3.14+ or Helm 4", chart_readme)
        self.assertIn("forward-compatible fix against the current schema", chart_readme)
        self.assertIn("Do not treat `helm rollback` as schema recovery", chart_readme)

    def test_direct_production_helm_example_binds_external_secret_version(self):
        chart_readme = (self.root / "deploy/helm/tickety/README.md").read_text()

        self.assertIn(
            "EXTERNAL_SECRET_RESOURCE_VERSION=\"$(kubectl get secret tickety-runtime-secrets",
            chart_readme,
        )
        self.assertIn(
            '--set-string existingSecretRolloutToken="$EXTERNAL_SECRET_RESOURCE_VERSION"',
            chart_readme,
        )
        self.assertIn("resolves this non-secret token", chart_readme)

    def test_upgrade_drains_all_old_database_writers_before_auth_schema_migration(self):
        deployer = (self.root / "deploy.sh").read_text()
        chart_readme = (self.root / "deploy/helm/tickety/README.md").read_text()
        deployment_docs = (self.root / "docs/deployment.md").read_text()
        sso_docs = (self.root / "docs/sso.md").read_text()

        self.assertIn("drain_database_writers_for_auth_schema_cutover()", deployer)
        self.assertIn(
            'app.kubernetes.io/instance=$RELEASE,app.kubernetes.io/component=backend',
            deployer,
        )
        self.assertIn(
            'app.kubernetes.io/instance=$RELEASE,app.kubernetes.io/component=worker',
            deployer,
        )
        self.assertIn('kubectl get deployment --namespace "$NAMESPACE"', deployer)
        self.assertIn("Expected exactly one backend Deployment", deployer)
        self.assertIn("Expected at most one worker Deployment", deployer)
        self.assertIn('kubectl scale --namespace "$NAMESPACE" "$backend_deployment" --replicas=0', deployer)
        self.assertIn('kubectl scale --namespace "$NAMESPACE" "$worker_deployment" --replicas=0', deployer)
        self.assertIn('kubectl rollout status --namespace "$NAMESPACE" "$backend_deployment"', deployer)
        self.assertIn('kubectl rollout status --namespace "$NAMESPACE" "$worker_deployment"', deployer)
        self.assertIn('kubectl get pods --namespace "$NAMESPACE"', deployer)
        self.assertIn('kubectl wait --namespace "$NAMESPACE" --for=delete "$pod"', deployer)
        self.assertIn("for component in backend worker; do", deployer)
        self.assertIn("while :; do", deployer)

        upgrade_guard = deployer.index(
            "  drain_database_writers_for_auth_schema_cutover\n",
            deployer.index("if [[ $RELEASE_OPERATION == upgrade ]]; then"),
        )
        helm_upgrade = deployer.index('    upgrade "$RELEASE" "$CHART_DIR"', upgrade_guard)
        self.assertLess(upgrade_guard, helm_upgrade)
        self.assertNotIn("drain_database_writers_for_auth_schema_cutover\n", deployer[deployer.index("else\n  # Do not use --atomic"):])

        for document in (chart_readme, deployment_docs, sso_docs):
            self.assertIn("0056", document)
        self.assertIn("SSO authorization states", chart_readme)
        self.assertIn("application maintenance window", chart_readme)
        self.assertIn("every old chart-managed\ndatabase-writing Pod", deployment_docs)
        self.assertIn("Users must authenticate again", sso_docs)
        self.assertIn("application\nremains unavailable", deployment_docs)
        self.assertIn("did not commit", deployment_docs)
        self.assertNotIn("leaves the prior release running", deployment_docs)

    def test_migration_job_fails_closed_before_schema_changes_for_unreadable_settings_secrets(self):
        migration_job = (
            self.root / "deploy/helm/tickety/templates/migration-job.yaml"
        ).read_text()
        dockerfile = (self.root / "Dockerfile").read_text()
        preflight = (
            self.root / "scripts/verify-settings-secret-encryption.py"
        ).read_text()
        encryption_docs = (
            self.root / "docs/settings-secret-encryption.md"
        ).read_text()

        command = (
            'command: ["/bin/sh", "-ec", "python '
            'scripts/verify-settings-secret-encryption.py && alembic upgrade head"]'
        )
        self.assertIn(command, migration_job)
        self.assertIn(
            "COPY --chown=tickety:tickety scripts/verify-settings-secret-encryption.py "
            "./scripts/verify-settings-secret-encryption.py",
            dockerfile,
        )
        self.assertIn(
            "COPY --chown=tickety:tickety scripts/reencrypt-settings-secrets.py "
            "./scripts/reencrypt-settings-secrets.py",
            dockerfile,
        )
        self.assertIn("_settings_encryption_keyring()", preflight)
        self.assertIn("inspect(db.get_bind()).get_table_names()", preflight)
        self.assertIn("if not table_names:", preflight)
        self.assertIn("db.query(SettingsRecord)", preflight)
        self.assertNotIn("_read_db_overrides", preflight)
        self.assertNotIn("allow-legacy-plaintext", preflight)
        self.assertIn("Helm upgrade gate", encryption_docs)
        self.assertIn("before schema migration", encryption_docs)

    def test_helm_requires_encryption_keyring_for_chart_managed_secret_and_documents_external_contract(self):
        secret_template = (
            self.root / "deploy/helm/tickety/templates/secret.yaml"
        ).read_text()
        values = (self.root / "deploy/helm/tickety/values.yaml").read_text()
        chart_readme = (self.root / "deploy/helm/tickety/README.md").read_text()
        encryption_docs = (
            self.root / "docs/settings-secret-encryption.md"
        ).read_text()

        self.assertIn("if not .Values.existingSecret", secret_template)
        self.assertIn(
            'index .Values.secrets "TICKETY_SETTINGS_ENCRYPTION_ACTIVE_KID"',
            secret_template,
        )
        self.assertIn(
            'index .Values.secrets "TICKETY_SETTINGS_ENCRYPTION_KEYS_JSON"',
            secret_template,
        )
        self.assertIn(
            "secrets.TICKETY_SETTINGS_ENCRYPTION_ACTIVE_KID is required",
            secret_template,
        )
        self.assertIn(
            "secrets.TICKETY_SETTINGS_ENCRYPTION_KEYS_JSON is required",
            secret_template,
        )
        self.assertNotIn("fail (printf", secret_template)
        self.assertIn("migration preflight never starts without its deployment-owned keyring", values)
        self.assertIn("TICKETY_SETTINGS_ENCRYPTION_KEYS_JSON", chart_readme)
        self.assertIn("externally managed `existingSecret`", encryption_docs)

    def test_settings_encryption_preflight_fails_for_missing_keyring_on_empty_database(self):
        script = self.root / "scripts/verify-settings-secret-encryption.py"
        with patch.object(
            settings,
            "_settings_encryption_keyring",
            side_effect=settings.SettingsEncryptionError("keyring missing"),
        ):
            namespace = runpy.run_path(str(script), run_name="settings_preflight")
            output = io.StringIO()
            with redirect_stdout(output):
                result = namespace["main"]()

        self.assertEqual(result, 1)
        self.assertIn("settings encryption preflight failed", output.getvalue())
        self.assertNotIn("keyring missing", output.getvalue())

    def test_settings_encryption_preflight_fails_closed_for_database_query_errors(self):
        script = self.root / "scripts/verify-settings-secret-encryption.py"
        with (
            patch.object(settings, "_settings_encryption_keyring"),
            patch(
                "app.backend.database.SessionLocal",
                side_effect=RuntimeError("database unavailable"),
            ),
        ):
            namespace = runpy.run_path(str(script), run_name="settings_preflight")
            output = io.StringIO()
            with redirect_stdout(output):
                result = namespace["main"]()

        self.assertEqual(result, 1)
        self.assertIn("settings encryption preflight failed", output.getvalue())
        self.assertNotIn("database unavailable", output.getvalue())

    def test_settings_encryption_preflight_rejects_unfenced_ciphertext_for_a_different_active_kid(self):
        script = self.root / "scripts/verify-settings-secret-encryption.py"
        session = MagicMock()
        inspector = MagicMock()
        inspector.get_table_names.return_value = ["settings"]
        session.get_bind.return_value = MagicMock()
        session.get.return_value = None
        row = MagicMock()
        row.value = "enc:v1:previous:opaque"
        session.query.return_value.filter.return_value.all.return_value = [row]
        with (
            patch.object(
                settings,
                "_settings_encryption_keyring",
                return_value=("current", {"current": b"x" * 32}),
            ),
            patch("app.backend.database.SessionLocal", return_value=session),
            patch("sqlalchemy.inspect", return_value=inspector),
        ):
            namespace = runpy.run_path(str(script), run_name="settings_preflight")
            output = io.StringIO()
            with redirect_stdout(output):
                result = namespace["main"]()

        self.assertEqual(result, 1)
        self.assertIn("settings encryption preflight failed", output.getvalue())
        self.assertNotIn("previous", output.getvalue())
        session.close.assert_called_once()

    def test_settings_encryption_preflight_allows_only_a_valid_keyring_on_a_fresh_database(self):
        script = self.root / "scripts/verify-settings-secret-encryption.py"
        session = MagicMock()
        inspector = MagicMock()
        inspector.get_table_names.return_value = []
        with (
            patch.object(
                settings,
                "_settings_encryption_keyring",
                return_value=("current", {"current": b"x" * 32}),
            ),
            patch("app.backend.database.SessionLocal", return_value=session),
            patch("sqlalchemy.inspect", return_value=inspector),
        ):
            namespace = runpy.run_path(str(script), run_name="settings_preflight")
            output = io.StringIO()
            with redirect_stdout(output):
                result = namespace["main"]()

        self.assertEqual(result, 0)
        self.assertIn("settings encryption preflight passed", output.getvalue())
        session.query.assert_not_called()
        session.close.assert_called_once()

    def test_settings_encryption_preflight_rejects_partial_or_initialized_schema_without_settings(self):
        script = self.root / "scripts/verify-settings-secret-encryption.py"
        # The third-party table was the remaining false-positive: the previous
        # "no known Tickety table" test would have accepted it and migrated an
        # unintended database.
        for table_names in (["users"], ["alembic_version"], ["third_party_audit"]):
            with self.subTest(table_names=table_names):
                session = MagicMock()
                inspector = MagicMock()
                inspector.get_table_names.return_value = table_names
                with (
                    patch.object(
                        settings,
                        "_settings_encryption_keyring",
                        return_value=("current", {"current": b"x" * 32}),
                    ),
                    patch("app.backend.database.SessionLocal", return_value=session),
                    patch("sqlalchemy.inspect", return_value=inspector),
                ):
                    namespace = runpy.run_path(str(script), run_name="settings_preflight")
                    output = io.StringIO()
                    with redirect_stdout(output):
                        result = namespace["main"]()

                self.assertEqual(result, 1)
                self.assertIn("settings encryption preflight failed", output.getvalue())
                session.query.assert_not_called()
                session.close.assert_called_once()

    def test_every_migration_entrypoint_runs_the_strict_encryption_preflight(self):
        compose = (self.root / "docker-compose.yml").read_text()
        microk8s_job = (
            self.root / "deploy/dev-microk8s/migration-job.yaml.tpl"
        ).read_text()
        gate = "python scripts/verify-settings-secret-encryption.py && alembic upgrade head"

        self.assertIn(gate, compose)
        self.assertIn(gate, microk8s_job)

    def test_production_baseline_and_pdbs_protect_only_replicated_public_workloads(self):
        production_values = (
            self.root / "deploy/examples/production-values.yaml"
        ).read_text()
        template = (
            self.root / "deploy/helm/tickety/templates/poddisruptionbudget.yaml"
        ).read_text()

        self.assertIn("backend:\n  # Pair with the frontend replicas", production_values)
        self.assertEqual(production_values.count("replicaCount: 2"), 2)
        self.assertIn("if ge (int .Values.backend.replicaCount) 2", template)
        self.assertIn("if ge (int .Values.frontend.replicaCount) 2", template)
        self.assertEqual(template.count("kind: PodDisruptionBudget"), 2)
        self.assertEqual(template.count("minAvailable: 1"), 2)
        self.assertNotIn('component" "worker")', template)
        self.assertNotIn('component" "postgresql")', template)

    def test_worker_shutdown_deadline_is_bounded_below_pod_grace(self):
        values = (self.root / "deploy/helm/tickety/values.yaml").read_text()
        schema = json.loads(
            (self.root / "deploy/helm/tickety/values.schema.json").read_text()
        )
        template = (self.root / "deploy/helm/tickety/templates/backend.yaml").read_text()

        self.assertIn("shutdownDeadlineSeconds: 20", values)
        deadline = schema["properties"]["worker"]["properties"]["shutdownDeadlineSeconds"]
        self.assertEqual(deadline, {"type": "integer", "minimum": 5, "maximum": 30})
        worker = template[template.index('name: {{ include "tickety.fullname" . }}-worker'):]
        self.assertIn("terminationGracePeriodSeconds: 45", worker)
        self.assertIn("WORKER_SHUTDOWN_DEADLINE_SECONDS", worker)

    def test_worker_uses_completed_callback_heartbeat_for_all_kubernetes_probes(self):
        values = (self.root / "deploy/helm/tickety/values.yaml").read_text()
        schema = json.loads(
            (self.root / "deploy/helm/tickety/values.schema.json").read_text()
        )
        template = (self.root / "deploy/helm/tickety/templates/backend.yaml").read_text()
        worker = template[template.index('name: {{ include "tickety.fullname" . }}-worker'):]

        self.assertIn("healthcheckMaxAgeSeconds: 120", values)
        self.assertEqual(
            schema["properties"]["worker"]["properties"]["healthcheckMaxAgeSeconds"],
            {"type": "integer", "minimum": 30, "maximum": 600},
        )
        self.assertIn("WORKER_HEALTHCHECK_MAX_AGE_SECONDS", worker)
        self.assertEqual(worker.count('"--healthcheck"'), 3)
        self.assertIn("startupProbe:", worker)
        self.assertIn("readinessProbe:", worker)
        self.assertIn("livenessProbe:", worker)

    def test_helm_rejects_worker_image_drift_and_configmap_credential_names(self):
        helpers = (self.root / "deploy/helm/tickety/templates/_helpers.tpl").read_text()
        configmap = (
            self.root / "deploy/helm/tickety/templates/configmap.yaml"
        ).read_text()
        schema = json.loads(
            (self.root / "deploy/helm/tickety/values.schema.json").read_text()
        )

        self.assertIn("worker.image.repository must match backend.image.repository", helpers)
        self.assertIn("worker.image.tag must match backend.image.tag", helpers)
        self.assertIn('include "tickety.backendImage" .', helpers)
        self.assertIn("config.extra.%s is reserved or may contain a credential", configmap)
        self.assertIn("TICKETY_SETTINGS_ENCRYPTION_", configmap)
        self.assertIn("sensitiveExtraKeyPattern", configmap)
        extra_name_rules = schema["properties"]["config"]["properties"]["extra"]["propertyNames"]["allOf"]
        self.assertTrue(any(rule.get("pattern") == "^[A-Z][A-Z0-9_]*$" for rule in extra_name_rules))
        self.assertTrue(any(
            rule.get("not", {}).get("pattern") == "^TICKETY_SETTINGS_ENCRYPTION_"
            for rule in extra_name_rules
        ))

    def test_values_schema_covers_migration_and_chart_metadata_inputs(self):
        schema = json.loads(
            (self.root / "deploy/helm/tickety/values.schema.json").read_text()
        )
        properties = schema["properties"]

        self.assertFalse(schema.get("additionalProperties", True))
        for key in ("nameOverride", "fullnameOverride", "migration", "podAnnotations", "podLabels"):
            self.assertIn(key, properties)
        migration = properties["migration"]
        self.assertEqual(
            migration["required"],
            ["activeDeadlineSeconds", "backoffLimit", "resources"],
        )
        self.assertEqual(
            migration["properties"]["resources"]["$ref"],
            "#/definitions/resourceRequirements",
        )
        self.assertFalse(migration.get("additionalProperties", True))

    def test_deployment_validator_exercises_helm_security_negative_cases(self):
        validator = (self.root / "scripts/validate-deployment.sh").read_text()

        self.assertIn("validation_existing_secret=tickety-validation-runtime-secrets", validator)
        self.assertIn("worker.image.tag=validation-image-drift", validator)
        self.assertIn("config.extra.AZURE_STORAGE_CONNECTION_STRING=validation-only", validator)
        self.assertIn("backend, worker, and migration images drift", validator)
        self.assertIn("settings-encryption material reached a ConfigMap", validator)

    def test_compose_worker_uses_the_same_completed_work_heartbeat(self):
        compose = (self.root / "docker-compose.yml").read_text()
        worker = compose[compose.index("  worker:\n"):compose.index("\n  frontend:\n")]

        self.assertIn('"python", "-m", "app.backend.worker", "--healthcheck"', worker)
        self.assertNotIn("os.kill(1, 0)", worker)
        self.assertIn("in-process watchdog exits", worker)

    def test_production_spreads_the_replicated_api_and_frontend(self):
        production_values = (
            self.root / "deploy/examples/production-values.yaml"
        ).read_text()
        backend = (self.root / "deploy/helm/tickety/templates/backend.yaml").read_text()
        frontend = (self.root / "deploy/helm/tickety/templates/frontend.yaml").read_text()

        self.assertIn(
            "frontend:\n  # Two public proxies preserve service through one Pod/node disruption.\n  replicaCount: 2\n  topologySpread:\n    # Keep the public proxy replicas on separate nodes when capacity permits.\n    enabled: true",
            production_values,
        )
        self.assertIn(
            "backend:\n  # Pair with the frontend replicas and the PDBs rendered by the chart.\n  replicaCount: 2\n  topologySpread:\n    # Avoid a single node taking both API replicas out of service.\n    enabled: true",
            production_values,
        )
        self.assertIn("backend.topologySpread.enabled", backend)
        self.assertIn('component" "backend")', backend)
        self.assertIn("frontend.topologySpread.enabled", frontend)
        self.assertIn('component" "frontend")', frontend)


if __name__ == "__main__":
    unittest.main()
