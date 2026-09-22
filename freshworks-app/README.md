# Tickety OPS Tower for Freshservice

This package retains the Freshservice sidebar and full-page placements, but it intentionally does not retrieve or display Tickety OPS Tower ticket intelligence. It presents an availability notice while a provider-authorized, server-side viewer authorization design is implemented.

## Prerequisites

- Freshworks CLI 10.1.9 and Node.js 24.11.x. Install the official Freshworks
  CLI before running the commands below; do not substitute the unrelated npm
  package named `fdk`.

## Local validation

From this directory:

```sh
npm install
fdk unit-test
fdk validate
fdk run
```

This disabled package has no installation parameters and no Tickety OPS Tower request template. It can be installed only to communicate the availability state; it is not a ticket-viewing integration.

After exercising both the full-page and ticket-sidebar locations in the local
simulator, stop `fdk run` and package the app:

```sh
npm run fdk-package
```

The installable artifact is written to `dist/freshworks-app.zip`. For a private
custom-app build that is not being submitted to the public Marketplace,
`npm run fdk-package` uses `fdk pack --skip-coverage` and then inspects the
generated archive to ensure it contains no retired request template or
browser-side authorization context. The retired package is a static HTML/CSS/SVG
notice: it loads neither the Freshworks app client nor JavaScript. The package
gate accepts only that fixed runtime asset set and the exact FDK packaging
metadata required for this app, and rejects executable markup or extra files.
Run `fdk unit-test` immediately before packaging: it invokes the same
`fdk-unit-test` script, then records the FDK report and hash that `fdk pack`
requires. `npm run fdk-unit-test` remains useful for fast local feedback, but
does not substitute for that FDK lifecycle step.

## Security state

Freshworks Data Method values describe the browser UI but are not a server-verifiable assertion of the current user or ticket. Freshworks Request Method keeps secure installation parameters out of browser code, but it does not add that missing authorization proof. Tickety OPS Tower therefore removed the bootstrap, session, and ticket-context endpoints; previously issued embedded tokens are rejected and the package contains no API request template, installation secret, Freshworks client loader, or executable browser code.

Do not re-enable the previous flow with an environment setting. A future implementation must use a per-user Freshservice OAuth authorization to make a server-side provider call for the requested ticket, fail closed on any denial or ambiguous provider result, and return local projection data only after that check succeeds. The existing Freshservice adapter remains read-only: it has no create, update, reply, note, attachment, or delete method.
