# Single sign-on with Microsoft Entra ID or Okta

Tickety supports one active OpenID Connect provider per deployment. Microsoft
Entra ID and Okta have presets, so the deployment only needs the provider's
tenant/domain, client ID, and client secret. The discovery URL and the sign-in
callback are derived automatically.

The callback registered with either provider must be exactly:

```text
https://<tickety-host>/api/auth/sso/callback
```

`FRONTEND_URL` must be the matching HTTPS origin, without a path. Apply database
migration `0011` before enabling SSO.

## Microsoft Entra ID

Create a Microsoft Entra **App registration** for a server-side web application:

1. Select the single-tenant account type for the Tickety organization's
   directory.
2. Add a **Web** redirect URI using the exact Tickety callback above.
3. Create a client secret. Copy the secret **value** when it is shown, rather
   than the secret ID.
4. Copy the **Application (client) ID** and **Directory (tenant) ID** from the
   app registration. Tickety intentionally requires the tenant GUID and does
   not accept `common`, `organizations`, or `consumers` authorities.
5. In the corresponding Enterprise application, assign only the users or
   groups that should be able to sign in. Requiring assignment is recommended.

Tickety requests only `openid email profile`; it does not call Microsoft Graph.
The preset follows Microsoft's tenant-specific OIDC discovery and validates the
ID token's signature, issuer, audience, expiry, and nonce. See Microsoft's
[OIDC protocol documentation](https://learn.microsoft.com/en-us/entra/identity-platform/v2-protocols-oidc)
and [ID-token claims reference](https://learn.microsoft.com/en-us/entra/identity-platform/id-token-claims-reference).

Environment configuration:

```dotenv
APP_MODE=production
LOGIN_REQUIRED=true
FRONTEND_URL=https://support.example.com
SSO_ENABLED=true
SSO_PROVIDER=entra
SSO_ENTRA_TENANT_ID=<directory-tenant-id-guid>
SSO_CLIENT_ID=<application-client-id>
SSO_CLIENT_SECRET=<client-secret-value>
SSO_ALLOWED_DOMAINS=example.com
SSO_AUTO_PROVISION=false
```

Helm configuration:

```yaml
config:
  sso:
    enabled: true
    provider: entra
    clientId: <application-client-id>
    entraTenantId: <directory-tenant-id-guid>
    oktaDomain: ""
    oktaAuthServerId: org
    discoveryUrl: ""
    allowedDomains: example.com
    autoProvision: false

secrets:
  SSO_CLIENT_SECRET: <client-secret-value>
```

When `existingSecret` is used, put `SSO_CLIENT_SECRET` in that Secret and update
`existingSecretRolloutToken` whenever the secret is rotated.

## Okta

Create an Okta app integration using **OIDC - OpenID Connect** and **Web
Application**:

1. Enable the Authorization Code grant.
2. Add the exact Tickety callback as a Sign-in redirect URI.
3. Copy the Client ID and Client Secret.
4. Assign the app only to the users or groups that should have Tickety access.
5. Copy the Okta organization domain, such as `company.okta.com`.

Tickety defaults to Okta's built-in org authorization server (`org`), which is
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
FRONTEND_URL=https://support.example.com
SSO_ENABLED=true
SSO_PROVIDER=okta
SSO_OKTA_DOMAIN=company.okta.com
SSO_OKTA_AUTH_SERVER_ID=org
SSO_CLIENT_ID=<okta-client-id>
SSO_CLIENT_SECRET=<okta-client-secret>
SSO_ALLOWED_DOMAINS=example.com
SSO_AUTO_PROVISION=false
```

The equivalent Helm block is:

```yaml
config:
  sso:
    enabled: true
    provider: okta
    clientId: <okta-client-id>
    entraTenantId: ""
    oktaDomain: company.okta.com
    oktaAuthServerId: org
    discoveryUrl: ""
    allowedDomains: example.com
    autoProvision: false

secrets:
  SSO_CLIENT_SECRET: <okta-client-secret>
```

## Account access and user experience

- Keep `SSO_AUTO_PROVISION=false` when Tickety access should be pre-approved.
  Create the local user with the same email first; the first verified SSO login
  links that user to the provider's immutable issuer and subject.
- With auto-provisioning enabled, a new SSO identity creates an active local
  user with the `agent` role. Identity-provider claims never grant Tickety
  administrator or supervisor roles.
- `SSO_ALLOWED_DOMAINS` is an additional comma-separated restriction. Provider
  application assignment remains the primary access boundary.
- Later email/name changes do not change the account binding. Deactivating the
  local Tickety user blocks SSO access.
- The login page makes the configured provider the primary action and keeps
  local password login behind a secondary choice. After SSO, users return to
  the protected page they originally requested. Tickety sign-out ends the local
  session; it does not sign the browser out of Entra ID or Okta.

## Verification and troubleshooting

Before opening traffic, verify the public non-secret status endpoint:

```sh
curl --fail --silent https://support.example.com/api/auth/sso/config
```

It should return `"enabled":true`, `"ready":true`, the intended provider, and
the exact redirect URI. Then test with an assigned user and confirm:

1. a protected destination is restored after authentication;
2. an unassigned or unprovisioned user gets a friendly denial and no session;
3. a deactivated local user cannot sign in;
4. local sign-out removes the Tickety session.

`ready:false` means a deployment-owned value is absent or invalid. A redirect
URI mismatch must be corrected at the provider; do not add alternate callbacks
or weaken the tenant/issuer checks. Provider discovery, token, JWKS, and
userinfo endpoints must resolve to public HTTPS addresses.

Generic OIDC remains available with `SSO_PROVIDER=<display name>` and
`SSO_DISCOVERY_URL=https://.../.well-known/openid-configuration`. Existing
Entra/Okta installations that already provide an explicit discovery URL remain
compatible, but the presets above are preferred.
