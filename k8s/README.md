# Legacy Kubernetes manifests

New installations should use the portable Helm chart in
[`deploy/helm/tickety`](../deploy/helm/tickety) and the workflows in
[`docs/deployment.md`](../docs/deployment.md). It accepts registry images,
release/namespace names, ingress or LoadBalancer configuration, persistent or
external PostgreSQL, and secret-manager supplied values.

The YAML files in this directory are retained only for the original local
development cluster workflow. They hard-code the `tickety` namespace,
`tickety-backend:latest` / `tickety-frontend:latest` local images with
`imagePullPolicy: Never`, a Traefik ingress host, and the local deployment
assumptions. They are not the supported path for generic Kubernetes or AKS.

Do not combine these legacy manifests with a Helm release in the same
namespace. For current deployment, upgrade, backup, verification, and removal
instructions, use [the deployment guide](../docs/deployment.md).
