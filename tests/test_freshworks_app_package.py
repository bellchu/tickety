import json
import pathlib
import subprocess
import tempfile
import unittest
import warnings
import zipfile


ROOT = pathlib.Path(__file__).resolve().parents[1] / "freshworks-app"
VERIFIER = ROOT / "scripts" / "verify-package.sh"


class FreshworksAppPackageTests(unittest.TestCase):
    def _source_archive_entries(self):
        source_entries = [
            (entry, (ROOT / entry).read_bytes())
            for entry in (
                "manifest.json",
                "config/iparams.json",
                "config/requests.json",
                "app/index.html",
                "app/styles/images/icon.svg",
                "app/styles/styles.css",
                "README.md",
                "package.json",
                "vitest.config.js",
                "tests/app.test.js",
                "tests/static-notice-policy.js",
            )
        ]
        return source_entries + [
            (".report.json", json.dumps({"lints": []})),
            ("digest.md5", "0" * 32),
        ]

    def _write_archive(self, entries, *, entries_are_raw=False):
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        archive_path = pathlib.Path(tempdir.name) / "freshworks-app.zip"
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for entry, content in entries:
                archive.writestr(entry if entries_are_raw else f"./{entry}", content)
        return archive_path

    @staticmethod
    def _fdk_entries(entries):
        return [(f"./{entry}", content) for entry, content in entries]

    def _verify_archive(self, archive_path):
        return subprocess.run(
            ["bash", str(VERIFIER), str(archive_path)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )

    @staticmethod
    def _replace_entry(entries, entry_to_replace, replacement):
        return [
            (entry, replacement if entry == entry_to_replace else content)
            for entry, content in entries
        ]

    def test_manifest_keeps_placements_but_declares_no_backend_requests(self):
        manifest = json.loads((ROOT / "manifest.json").read_text())
        self.assertEqual(manifest["platform-version"], "3.0")
        self.assertIn("full_page_app", manifest["modules"]["common"]["location"])
        self.assertIn("ticket_sidebar", manifest["modules"]["service_ticket"]["location"])
        self.assertNotIn("requests", manifest["modules"]["common"])

    def test_disabled_package_has_no_parameter_or_request_surface(self):
        iparams = json.loads((ROOT / "config" / "iparams.json").read_text())
        requests = json.loads((ROOT / "config" / "requests.json").read_text())
        markup = (ROOT / "app" / "index.html").read_text()

        self.assertEqual(iparams, {})
        self.assertEqual(requests, {})
        self.assertFalse((ROOT / "app" / "scripts" / "app.js").exists())
        for legacy_identifier in (
            "invokeTemplate",
            "ticketyBootstrap",
            "ticketyRedeem",
            "ticketyTicketContext",
            "bootstrap_secret",
            "loggedInUser",
            "currentHost",
            "external_ticket_id",
        ):
            with self.subTest(legacy_identifier=legacy_identifier):
                self.assertNotIn(legacy_identifier, markup)
        self.assertNotIn("{{{appclient}}}", markup)
        self.assertNotIn("<script", markup.lower())

    def test_disabled_notice_explains_that_no_ticket_data_is_displayed(self):
        markup = (ROOT / "app" / "index.html").read_text()
        self.assertIn("provider-authorized server-side check", markup)
        self.assertIn("No ticket data is requested or displayed", markup)

    def test_package_command_invokes_the_archive_surface_gate(self):
        package = json.loads((ROOT / "package.json").read_text())
        verifier = (ROOT / "scripts" / "verify-package.sh").read_text()
        self.assertIn("verify-package.sh", package["scripts"]["fdk-package"])
        self.assertIn("unzip -Z1", verifier)
        self.assertIn("app/index.html", verifier)
        self.assertIn("static_runtime_files", verifier)
        self.assertIn("fdk_pack_metadata_files", verifier)
        self.assertIn("unexpected archive file", verifier)
        self.assertNotIn("app/scripts/app.js", verifier)
        self.assertIn("config/iparams.json", verifier)
        self.assertIn("config/requests.json", verifier)

    def test_archive_surface_gate_accepts_the_current_disabled_package(self):
        result = self._verify_archive(self._write_archive(self._source_archive_entries()))
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_archive_surface_gate_rejects_noncanonical_and_colliding_paths(self):
        for malicious_entry in (
            "manifest.json",
            "././manifest.json",
            "./../manifest.json",
            ".//manifest.json",
            "./config/./requests.json",
            "./app//styles/styles.css",
        ):
            with self.subTest(malicious_entry=malicious_entry):
                archive = self._write_archive(
                    self._fdk_entries(self._source_archive_entries())
                    + [(malicious_entry, "{}")],
                    entries_are_raw=True,
                )
                result = self._verify_archive(archive)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("archive entry", result.stderr)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            archive = self._write_archive(
                self._fdk_entries(self._source_archive_entries())
                + [("./manifest.json", "{}")],
                entries_are_raw=True,
            )
        result = self._verify_archive(archive)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate or case-colliding", result.stderr)

        archive = self._write_archive(
            self._fdk_entries(self._source_archive_entries())
            + [("./Manifest.json", "{}")],
            entries_are_raw=True,
        )
        result = self._verify_archive(archive)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate or case-colliding", result.stderr)

    def test_archive_surface_gate_rejects_invalid_disabled_access_contracts(self):
        manifest = json.loads((ROOT / "manifest.json").read_text())
        manifest["metadata"] = {"requests": {"retired": {}}}
        external_location_manifest = json.loads((ROOT / "manifest.json").read_text())
        external_location_manifest["modules"]["common"]["location"]["full_page_app"][
            "url"
        ] = "https://example.invalid/embedded.html"
        cases = (
            (
                "nested manifest requests",
                self._replace_entry(
                    self._source_archive_entries(),
                    "manifest.json",
                    json.dumps(manifest),
                ),
            ),
            (
                "non-static manifest location",
                self._replace_entry(
                    self._source_archive_entries(),
                    "manifest.json",
                    json.dumps(external_location_manifest),
                ),
            ),
            (
                "invalid iparams JSON",
                self._replace_entry(
                    self._source_archive_entries(), "config/iparams.json", "{"
                ),
            ),
            (
                "nonempty requests config",
                self._replace_entry(
                    self._source_archive_entries(),
                    "config/requests.json",
                    json.dumps({"legacy": {}}),
                ),
            ),
        )
        for name, entries in cases:
            with self.subTest(name=name):
                result = self._verify_archive(self._write_archive(entries))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("disabled-access JSON contract", result.stderr)

    def test_archive_surface_gate_allows_only_static_assets(self):
        index_html = (ROOT / "app" / "index.html").read_text() + "\n<script>window[\"app\"]</script>"
        cases = (
            (
                "inline computed-property client access",
                self._replace_entry(
                    self._source_archive_entries(), "app/index.html", index_html
                ),
            ),
            (
                "inline event handler",
                self._replace_entry(
                    self._source_archive_entries(),
                    "app/index.html",
                    (ROOT / "app" / "index.html").read_text()
                    + "\n<body onload='window[\"app\"]'></body>",
                ),
            ),
            (
                "solidus-delimited inline event handler",
                self._replace_entry(
                    self._source_archive_entries(),
                    "app/index.html",
                    (ROOT / "app" / "index.html").read_text()
                    + "\n<body/onload='window[\"app\"]'></body>",
                ),
            ),
            (
                "Freshworks client template",
                self._replace_entry(
                    self._source_archive_entries(),
                    "app/index.html",
                    (ROOT / "app" / "index.html").read_text()
                    + "\n<img src=\"{{{appclient}}}\" />",
                ),
            ),
            (
                "additional JavaScript with computed-property client access",
                self._source_archive_entries()
                + [
                    (
                        "app/scripts/extra.js",
                        'window["app"]["initialized"]().then((client) => client["data"]["get"]("ticket"));',
                    )
                ],
            ),
            (
                "additional HTML",
                self._source_archive_entries()
                + [("app/views/extra.html", "<p>unexpected</p>")],
            ),
            (
                "non-browser extension",
                self._source_archive_entries()
                + [("app/notes.txt", "unexpected")],
            ),
        )
        for name, entries in cases:
            with self.subTest(name=name):
                result = self._verify_archive(self._write_archive(entries))
                self.assertNotEqual(result.returncode, 0)
                self.assertRegex(
                    result.stderr,
                    r"(executable script markup|inline event handler|Freshworks client template|unexpected archive file)",
                )

    def test_archive_surface_gate_rejects_external_resources_and_navigation(self):
        cases = (
            (
                "external image",
                "app/index.html",
                (ROOT / "app" / "index.html").read_text()
                + '\n<img src="https://collector.invalid/pixel" />',
            ),
            (
                "meta refresh",
                "app/index.html",
                (ROOT / "app" / "index.html").read_text()
                + '\n<meta http-equiv="refresh" content="0;url=https://collector.invalid/" />',
            ),
            (
                "CSS import",
                "app/styles/styles.css",
                (ROOT / "app" / "styles" / "styles.css").read_text()
                + '\n@import url("https://collector.invalid/style.css");',
            ),
        )
        for name, entry, replacement in cases:
            with self.subTest(name=name):
                result = self._verify_archive(
                    self._write_archive(
                        self._replace_entry(
                            self._source_archive_entries(), entry, replacement
                        )
                    )
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("static navigation contract", result.stderr)

    def test_archive_surface_gate_requires_sanitized_fdk_metadata(self):
        result = self._verify_archive(
            self._write_archive(
                self._replace_entry(
                    self._source_archive_entries(),
                    ".report.json",
                    json.dumps({"coverage": {}}),
                )
            )
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("disabled-access JSON contract", result.stderr)

        result = self._verify_archive(
            self._write_archive(
                self._replace_entry(
                    self._source_archive_entries(), ".report.json", "not JSON"
                )
            )
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("disabled-access JSON contract", result.stderr)

        result = self._verify_archive(
            self._write_archive(
                self._source_archive_entries() + [(".usage.json", json.dumps([]))]
            )
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        result = self._verify_archive(
            self._write_archive(
                self._source_archive_entries() + [(".usage.json", json.dumps({}))]
            )
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("disabled-access JSON contract", result.stderr)

    def test_ci_builds_and_verifies_the_actual_freshworks_archive(self):
        workflow = (ROOT.parent / ".github" / "workflows" / "ci.yml").read_text()
        freshworks_job = workflow.split("  freshworks-app:", 1)[1].split(
            "\n  backend:", 1
        )[0]
        package = json.loads((ROOT / "package.json").read_text())
        self.assertIn("node-version: 24.11.0", freshworks_job)
        self.assertEqual(package["packageManager"], "npm@11.6.1")
        self.assertIn("npm --version | grep -Fx '11.6.1'", freshworks_job)
        self.assertNotIn("npm@12", freshworks_job)
        self.assertIn("https://cdn.freshdev.io/fdk/latest-v24.tgz", freshworks_job)
        self.assertIn("npm --version | grep -Eq '^11[.]'", freshworks_job)
        self.assertIn("fdk version", freshworks_job)
        self.assertIn("fdk unit-test", freshworks_job)
        self.assertIn("fdk validate", freshworks_job)
        self.assertIn("git diff --exit-code -- manifest.json package.json", freshworks_job)
        self.assertIn("npm run fdk-package", freshworks_job)
        self.assertIn("rm -f dist/freshworks-app.zip", freshworks_job)
        self.assertIn("bash scripts/verify-package.sh dist/freshworks-app.zip", freshworks_job)


if __name__ == "__main__":
    unittest.main()
