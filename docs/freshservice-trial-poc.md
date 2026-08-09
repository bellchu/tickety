# Freshservice trial POC

Tickety supports a Freshservice trial as an isolated proof-of-concept environment. A trial binding is intentionally not promotable into a production deployment: repeat validation against a separately configured production binding instead.

## Deployment boundary

Run the POC as a dedicated Tickety deployment with:

```env
APP_MODE=production
TICKETY_DEPLOYMENT_CLASS=poc
FRESHSERVICE_API_KEY=replace-with-a-trial-only-key
```

The POC must use a separate database, cache, secrets, hostname, and encryption keys. Do not reuse a production Freshservice API key or Tickety data store. The credential is referenced as `env://freshservice`; it is never accepted or returned by the binding API.

## Binding lifecycle

The protected admin API exposes a fail-closed lifecycle:

1. `POST /admin/integrations/bindings` creates a `trial` binding with the canonical `*.freshservice.com` account host and an expiry time.
2. `POST /admin/integrations/bindings/{binding_id}/validate` probes Freshservice and records a capability manifest.
3. `POST /admin/integrations/bindings/{binding_id}/activate` succeeds only after the required `ticket.read` capability is supported.
4. `POST /admin/integrations/bindings/{binding_id}/suspend` stops the binding from being selected for synchronization.

Use `GET /admin/integrations/bindings` and `GET /admin/integrations/bindings/{binding_id}/capabilities` to inspect state without exposing credentials.

Only one Freshservice binding may be active in a Tickety deployment. Trial bindings expire automatically when the worker or integration endpoints next evaluate them. The maximum creation window is 21 days, allowing a 14-day trial plus a small setup buffer.

## Isolation guarantees in this phase

Synced tickets, agent mappings, sync cursors, webhook delivery digests, and adapter caches are scoped by `binding_id`. The active binding selects its own canonical host and workspace configuration. Existing installations continue to use the `legacy` scope until a binding is activated.

The capability probe verifies ticket and agent reads and publishes explicit unsupported or unknown states for unverified features. A Freshworks custom-app package now provides sidebar/full-page placement and hashed, short-lived session bootstrap. Status/priority write-back is implemented with idempotency and conflict records but remains locked until agent identity is cryptographically verified. Replies, notes, attachments, and service-request parity are not yet claimed.

## Suggested 14-day sequence

- Days 1–2: deploy the isolated POC, create the binding, run validation, and confirm the capability evidence.
- Days 3–5: activate read-only synchronization and verify tenant/workspace isolation.
- Days 6–9: test webhook ingestion, retries, duplicate delivery handling, and expiry behavior.
- Days 10–12: validate the Freshworks app/session flow and complete agent-level OAuth before enabling guarded write-back.
- Days 13–14: export evidence, suspend the trial binding, and decide whether to perform a clean production validation.

## Remaining implementation phases

The in-product app, one-time session bootstrap, and the first guarded status/priority operation are scaffolded. The next security gate is agent-level OAuth proof, followed by replies, private notes, attachments, and service-request parity. See `freshworks-app/README.md` for installation and validation details.
