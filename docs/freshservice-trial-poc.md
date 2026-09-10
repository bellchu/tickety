# Freshservice trial POC

Tickety OPS Tower supports a Freshservice trial as an isolated proof-of-concept environment. A trial binding is intentionally not promotable into a production deployment: repeat validation against a separately configured production binding instead.

## Deployment boundary

Run the POC as a dedicated Tickety OPS Tower deployment with:

```env
APP_MODE=production
TICKETY_DEPLOYMENT_CLASS=poc
FRESHSERVICE_API_KEY=replace-with-a-trial-only-key
FRESHSERVICE_OAUTH_SCOPES="freshservice.tickets.view freshservice.tickets.conversations.view freshservice.agents.manage freshservice.requesters.view"
```

The POC must use a separate database, cache, secrets, hostname, and encryption keys. Do not reuse a production Freshservice API key or Tickety OPS Tower data store. The credential is referenced as `env://freshservice`; it is never accepted or returned by the binding API. Use a dedicated Freshservice integration agent whose role can view the required records but cannot create, edit, reply, add notes, attach files, or delete. Freshservice uses the `freshservice.agents.manage` OAuth scope for the agent-list read endpoint and `freshservice.requesters.view` for requester/contact profiles, so the provider role is the required second layer of least privilege.

Tickety OPS Tower users and Freshservice users are separate identity domains. Directory refresh stores provider agents and requesters in `external_users` for read-only ticket context; it never creates, matches, merges, updates, authenticates, authorizes, or awards points to a Tickety OPS Tower account. Manage Tickety OPS Tower login credentials and roles only through the local user roster.

Use `POST /admin/sync/external-users` to refresh the provider snapshot and `GET /admin/external-users` to read it. Both routes require an authenticated Tickety OPS Tower administrator or supervisor session; provider identities cannot call these administrative APIs.

## Binding lifecycle

The protected admin API exposes a fail-closed lifecycle:

1. `POST /admin/integrations/bindings` creates a `trial` binding with the canonical `*.freshservice.com` account host and an expiry time.
2. `POST /admin/integrations/bindings/{binding_id}/validate` probes Freshservice and records a capability manifest.
3. `POST /admin/integrations/bindings/{binding_id}/activate` succeeds only after the required `ticket.read` capability is supported.
4. `POST /admin/integrations/bindings/{binding_id}/suspend` stops the binding from being selected for synchronization.

Use `GET /admin/integrations/bindings` and `GET /admin/integrations/bindings/{binding_id}/capabilities` to inspect state without exposing credentials.

Only one Freshservice binding may be active in a Tickety OPS Tower deployment. Trial bindings expire automatically when the worker or integration endpoints next evaluate them. The maximum creation window is 21 days, allowing a 14-day trial plus a small setup buffer.

## Isolation guarantees in this phase

Synced tickets, external user directory records, sync cursors, webhook delivery digests, and adapter caches are scoped by `binding_id`. External users have no foreign key or account mapping to Tickety OPS Tower users. The active binding selects its own canonical host and workspace configuration. Existing installations continue to use the `legacy` scope until a binding is activated.

The capability probe performs only ticket, agent, and requester reads. Its manifest declares `integration.mode=read_only`; ticket creation, updates, replies, notes, attachments, and service-request creation are permanently unsupported. The Freshworks custom app provides sidebar/full-page placement and hashed, short-lived external sessions, then reads the synchronized Tickety OPS Tower projection. Those sessions never become Tickety OPS Tower user sessions and the package contains no mutation request template or write controls.

## Suggested 14-day sequence

- Days 1–2: deploy the isolated POC, create the binding, run validation, and confirm the capability evidence.
- Days 3–5: activate read-only synchronization and verify tenant/workspace isolation.
- Days 6–9: test webhook ingestion, retries, duplicate delivery handling, and expiry behavior.
- Days 10–12: validate the Freshworks app/session flow, read-only OAuth allowlist, and provider-role permissions.
- Days 13–14: export evidence, suspend the trial binding, and decide whether to perform a clean production validation.

## Remaining implementation phases

The in-product app and one-time session bootstrap are implemented. Future provider adapters must preserve the same one-way contract: import authoritative ITSM data and keep all Tickety OPS Tower intelligence local. See `freshworks-app/README.md` for installation and validation details.
