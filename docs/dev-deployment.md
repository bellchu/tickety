# Development deployment on MicroK8s

The `dev` branch has one isolated, non-production release path. Configure its
environment-specific destination locally:

- public origin: `TICKETY_DEV_PUBLIC_HOST`
- SSH target: `TICKETY_DEV_SSH_ALIAS`, `TICKETY_DEV_SSH_USER`, and
  `TICKETY_DEV_SSH_HOST`
- runtime: the existing single-node MicroK8s `tickety` namespace
- registry: the host-only `localhost:32000` MicroK8s registry
- release archive: `/srv/tickety-dev/releases/<full-git-sha>`
- release command: `scripts/deploy-dev-microk8s.sh`

This path is not production evidence and never changes the fixed OCI
Kubernetes production release path. All discovery and release actions run
through the configured SSH/CLI channel.

The command accepts no target or branch flags. It requires `dev`, fetches
`origin/dev`, and requires both SHAs to match. It builds a `git archive` from
that committed object, verifies its SHA-256 on the host, and retains the archive
beside the immutable extracted release. Working-tree changes cannot enter the
image. Existing secrets remain in `tickety-secrets` and never enter Git or
command output.

Each release builds unique backend and frontend images, creates and validates a
custom-format PostgreSQL backup, runs `alembic upgrade head` as a bounded Job,
records prior image tags, rolls out only Tickety's three deployments, and checks
the public readiness, backend SHA, frontend build manifest, ingress hostname,
and Cloudflared service. It explicitly restores one replica for each Tickety
deployment after a maintenance scale-down. The release also keeps the shared CoreDNS forwarder in
`prefer_udp` mode because the host-provided upstream resolver accepts UDP but
not DNS over TCP. Verification sends a TCP query to CoreDNS and requires a
public answer. The backend and worker pod specifications also advertise EDNS0,
which keeps long provider CNAME answers on the supported UDP path; verification
resolves the currently configured Foundry hostname from the running backend's
actual network context. Duplicate Docker builder copies are removed only after
MicroK8s has pulled and verified the registry images.

```sh
scripts/validate-dev-deployment.sh
export TICKETY_DEV_SSH_ALIAS=<ssh-alias>
export TICKETY_DEV_SSH_HOST=<ssh-host>
export TICKETY_DEV_SSH_USER=<ssh-user>
export TICKETY_DEV_PUBLIC_HOST=<dev-hostname>
scripts/deploy-dev-microk8s.sh
```

If backup, migration, rollout, or verification fails, the release stops. Prior
image tags are recorded in `PREVIOUS_IMAGES`, and registry images remain for
rollback. Restoring across an incompatible migration requires the matching
verified database backup.
