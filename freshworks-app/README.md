# Tickety for Freshservice

This read-only Freshworks custom app renders in `service_ticket.ticket_sidebar` and `common.full_page_app`. It uses Freshworks Data Method for UI context and Request Method for every Tickety API call; the secure installation secret is never read by browser code.

## Prerequisites

- An isolated Tickety deployment with `APP_MODE=production` and `TICKETY_DEPLOYMENT_CLASS=poc`.
- An active Freshservice trial binding and synchronized external user directory.
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

Bootstrap codes are single use and expire after 90 seconds. Embedded bearer sessions expire after 10 minutes and are scoped to one binding, provider agent, workspace, and ticket. Tickety stores only SHA-256 token digests. The provider agent remains an external identity and is never converted into a Tickety login or role.

The app package declares only bootstrap, session redemption, and ticket-context request templates. There is no mutation template or UI control. Tickety's Freshservice adapter likewise has no create, update, reply, note, attachment, or delete method.

Use a dedicated view-only Freshservice integration agent. OAuth is constrained to `freshservice.tickets.view freshservice.agents.manage freshservice.requesters.view`; Freshservice requires the agent scope for listing agents, so the integration agent's provider role must independently deny agent and ticket mutations.
