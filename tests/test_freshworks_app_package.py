import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1] / "freshworks-app"


class FreshworksAppPackageTests(unittest.TestCase):
    def test_manifest_declares_sidebar_full_page_and_all_templates(self):
        manifest = json.loads((ROOT / "manifest.json").read_text())
        self.assertEqual(manifest["platform-version"], "3.0")
        self.assertIn("full_page_app", manifest["modules"]["common"]["location"])
        self.assertIn("ticket_sidebar", manifest["modules"]["service_ticket"]["location"])
        self.assertEqual(
            set(manifest["modules"]["common"]["requests"]),
            {
                "ticketyBootstrap",
                "ticketyRedeem",
                "ticketyTicketContext",
                "ticketyTicketWriteback",
            },
        )

    def test_secret_is_secure_and_only_substituted_into_request_headers(self):
        iparams = json.loads((ROOT / "config" / "iparams.json").read_text())
        requests = json.loads((ROOT / "config" / "requests.json").read_text())
        browser = (ROOT / "app" / "scripts" / "app.js").read_text()
        self.assertTrue(iparams["bootstrap_secret"]["secure"])
        self.assertNotIn("bootstrap_secret", browser)
        for name in ("ticketyBootstrap", "ticketyRedeem"):
            self.assertEqual(
                requests[name]["schema"]["headers"]["X-Tickety-App-Secret"],
                "<%= iparam.bootstrap_secret %>",
            )

    def test_writeback_template_is_ticket_scoped_and_idempotent(self):
        requests = json.loads((ROOT / "config" / "requests.json").read_text())
        schema = requests["ticketyTicketWriteback"]["schema"]
        self.assertEqual(schema["method"], "PATCH")
        self.assertIn("<%= context.external_ticket_id %>", schema["path"])
        self.assertEqual(
            schema["headers"]["Idempotency-Key"],
            "<%= context.idempotency_key %>",
        )


if __name__ == "__main__":
    unittest.main()
