# Tickety for Freshservice

This Freshworks custom app renders in `service_ticket.ticket_sidebar` and `common.full_page_app`. It uses Freshworks Data Method for UI context and Request Method for every Tickety API call; the secure installation secret is never read by browser code.

## Prerequisites

- An isolated Tickety deployment with `APP_MODE=production` and `TICKETY_DEPLOYMENT_CLASS=poc`.
- An active Freshservice trial binding and synchronized agent mappings.
- A public HTTPS Tickety API hostname.
- A random `FRESHWORKS_APP_BOOTSTRAP_SECRET` of at least 32 characters. Configure the same value as the app's secure `bootstrap_secret` installation parameter.
- Freshworks CLI 10.x and its compatible Node.js 24.x runtime.

## Local validation

From this directory:

```sh
fdk validate
fdk run
```

During installation, provide the Tickety API hostname without `https://`, the UUID returned by the binding API, and the bootstrap secret. Select the same Freshservice account and workspace represented by the binding.

## Security state

Bootstrap codes are single use and expire after 90 seconds. Embedded bearer sessions expire after 10 minutes and are scoped to one binding, mapped agent, workspace, and ticket. Tickety stores only SHA-256 token digests.

The current Data Method agent identifier is treated as mapped context, not cryptographic identity proof. Ticket write-back therefore remains fail-closed until the binding capability `freshworks.trusted_agent_identity` is verified as `supported`. The intended completion path is Freshworks agent-level OAuth on platform 3.1, with provider authorization applied to every context and write request. Do not manually override that capability merely to unlock the POC.

Once identity is verified, the implemented first write operation supports status and priority. It requires an idempotency key and compares the current provider `updated_at` value before changing Freshservice. Version mismatches are recorded as conflicts and return HTTP 409.
