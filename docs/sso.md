# Single sign-on with Microsoft Entra ID or Okta

Tickety OPS Tower supports one active OpenID Connect provider per deployment. Microsoft
Entra ID and Okta have presets, so the deployment only needs the provider's
tenant/domain, client ID, and client secret. The discovery URL and the sign-in
callback are derived automatically.

The callback registered with either provider must be exactly:

```text
https://tickety.example.com/api/auth/sso/callback
```

`FRONTEND_URL` must be the matching HTTPS origin, without a path. Apply database
migration `0011` before enabling SSO.

## Configure from Tickety OPS Tower Settings

The preferred workflow is **Settings → Access → Security & Authentication**.
An authenticated Tickety OPS Tower administrator can select Entra or Okta, enter the
provider values, group allowlist, and client secret, then enable SSO. These
values are stored as administrator-approved settings and reload after a restart;
`TICKETY_ADMIN_SETTINGS_PORTAL_ENABLED` is not required for SSO configuration.
Secrets are masked on every settings response and are never returned to the
browser. Runtime mode, `FRONTEND_URL`, login enforcement, cookies, CORS, and the
callback path remain deployment-owned security boundaries.

When switching from Entra to Okta (or changing the client ID), re-enter the new
provider's client secret in the same save. Tickety OPS Tower deliberately refuses to reuse
the previous provider's secret. The ignored Compose `.env` values below remain
available for initial bootstrap and break-glass recovery.

## Microsoft Entra ID

Create a Microsoft Entra **App registration** for a server-side web application:

1. Select the single-tenant account type for the Tickety OPS Tower organization's
   directory.
2. Add a **Web** redirect URI using the exact Tickety OPS Tower callback above.
3. Create a client secret. Copy the secret **value** when it is shown, rather
   than the secret ID.
4. Copy the **Application (client) ID** and **Directory (tenant) ID** from the
   app registration. Tickety OPS Tower intentionally requires the tenant GUID and does
   not accept `common`, `organizations`, or `consumers` authorities.
5. In the corresponding Enterprise application, assign only the users or
   groups that should be able to sign in. Requiring assignment is recommended.
6. Create the **IT agents** security group and copy its immutable **Object ID**.
   In the app registration's Token configuration, add the `groups` claim and
   select **Groups assigned to the application**. Assign IT agents to the
   enterprise application and configure that Object ID in Tickety OPS Tower. Do not use
   the editable group display name as an authorization boundary.

Tickety OPS Tower requests only `openid email profile`; it does not call Microsoft Graph.
The preset follows Microsoft's tenant-specific OIDC discovery and validates the
ID token's signature, issuer, audience, expiry, and nonce. See Microsoft's
[OIDC protocol documentation](https://learn.microsoft.com/en-us/entra/identity-platform/v2-protocols-oidc)
and [ID-token claims reference](https://learn.microsoft.com/en-us/entra/identity-platform/id-token-claims-reference).

Environment configuration:

```dotenv
APP_MODE=production
LOGIN_REQUIRED=true
FRONTEND_URL=https://tickety.example.com
SSO_ENABLED=true
SSO_PROVIDER=entra
SSO_ENTRA_TENANT_ID=<directory-tenant-id-guid>
SSO_CLIENT_ID=<application-client-id>
SSO_CLIENT_SECRET=<client-secret-value>
SSO_ALLOWED_DOMAINS=example.com
SSO_ALLOWED_GROUP_IDS=<it-agents-group-object-id-guid>
SSO_AUTO_PROVISION=false
```

## Okta

Create an Okta app integration using **OIDC - OpenID Connect** and **Web
Application**:

1. Enable the Authorization Code grant.
2. Add the exact Tickety OPS Tower callback as a Sign-in redirect URI.
3. Copy the Client ID and Client Secret.
4. Assign the app only to the users or groups that should have Tickety OPS Tower access.
5. Copy the Okta organization domain, such as `company.okta.com`.

Tickety OPS Tower defaults to Okta's built-in org authorization server (`org`), which is
the simplest choice for OIDC SSO. Enter `default` or another authorization
server ID only when that custom server and its access policy are already
configured. Okta documents that custom authorization servers can require the
API Access Management product in production; see [Okta authorization
servers](https://developer.okta.com/docs/concepts/auth-servers/) and the
[redirect sign-in guide](https://developer.okta.com/docs/guides/sign-into-web-app-redirect/main/).

Environment configuration:

```dotenv
APP_MODE=production
LOGIN_REQUIRED=true
FRONTEND_URL=https://tickety.example.com
SSO_ENABLED=true
SSO_PROVIDER=okta
SSO_OKTA_DOMAIN=company.okta.com
SSO_OKTA_AUTH_SERVER_ID=org
SSO_CLIENT_ID=<okta-client-id>
SSO_CLIENT_SECRET=<okta-client-secret>
SSO_ALLOWED_DOMAINS=example.com
SSO_ALLOWED_GROUP_IDS=<okta-group-id-if-required>
SSO_AUTO_PROVISION=false
```

## Account access and user experience

- Keep `SSO_AUTO_PROVISION=false` when Tickety OPS Tower access should be pre-approved.
  Create the local user with the same email first; the first verified SSO login
  links that user to the provider's immutable issuer and subject.
- With auto-provisioning enabled, a new SSO identity creates an active local
  user with the `agent` role. Identity-provider claims never grant Tickety OPS Tower
  administrator or supervisor roles.
- `SSO_ALLOWED_DOMAINS` is an additional comma-separated restriction. Provider
  application assignment remains the primary access boundary.
- `SSO_ALLOWED_GROUP_IDS` is a comma-separated, fail-closed group allowlist.
  Entra values must be group Object ID GUIDs. Okta may use group IDs emitted by
  its `groups` claim. When configured, at least one signed token/userinfo group
  must match. Entra group-overage tokens are rejected; keep the recommended
  “groups assigned to the application” claim mode so the IT agents group is
  emitted without requiring Microsoft Graph permissions.
- Later email/name changes do not change the account binding. Deactivating the
  local Tickety OPS Tower user blocks SSO access.
- The login page makes the configured provider the primary action and keeps
  local password login behind a secondary choice. After SSO, users return to
  the protected page they originally requested. Tickety OPS Tower sign-out ends the local
  session; it does not sign the browser out of Entra ID or Okta.

## Verification and troubleshooting

Before opening traffic, verify the public non-secret status endpoint:

```sh
curl --fail --silent https://tickety.example.com/api/auth/sso/config
```

It should return `"enabled":true`, `"ready":true`, the intended provider, and
the exact redirect URI. Then test with an assigned user and confirm:

1. a protected destination is restored after authentication;
2. an unassigned or unprovisioned user gets a friendly denial and no session;
3. a deactivated local user cannot sign in;
4. local sign-out removes the Tickety OPS Tower session.

`ready:false` means a deployment-owned value is absent or invalid. A redirect
URI mismatch must be corrected at the provider; do not add alternate callbacks
or weaken the tenant/issuer checks. Provider discovery, token, JWKS, and
userinfo endpoints must resolve to public HTTPS addresses.

Generic OIDC remains available with `SSO_PROVIDER=<display name>` and
`SSO_DISCOVERY_URL=https://.../.well-known/openid-configuration`. Existing
Entra/Okta installations that already provide an explicit discovery URL remain
compatible, but the presets above are preferred.
