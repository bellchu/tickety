# Tickety project rules

1. 以将 `tickety.imbell.com` 误认为生产环境为耻，以将 `tickety.situ.io` 作为指定生产环境为荣
   - 适用范围：所有生产部署、发布验证、监控、链接与部署文档。
   - 必需行为：生产部署与验证必须以 `https://tickety.situ.io` 为目标；执行前通过项目现有的可审计 CLI、API 或基础设施即代码流程确认其后端目标。
   - 禁止行为：不得将 `tickety.imbell.com` 当作生产环境，也不得用其健康状态或页面结果替代生产验证。
   - 完成证据：部署后须在 `https://tickety.situ.io` 验证就绪状态和预期构建版本，并保留可审计的命令、差异或响应证据。

2. 以每次重新猜测部署目标为耻，以复用固定目标映射为荣
   - 适用范围：部署到 `tickety.situ.io` 或 `tickety.imbell.com`，以及对应的发布前后验证。
   - 固定生产映射：`https://tickety.situ.io` 使用 SSH 别名 `oci`、K3s 命名空间 `tickety-standalone` 与 `sudo -n k3s kubectl`；生产镜像在 K3s containerd 中使用 `localhost/tickety-backend:<tag>` 与 `localhost/tickety-frontend:<tag>`，并以 `imagePullPolicy: Never` 发布。
   - 固定别名映射：`https://tickety.imbell.com` 使用本机 Kubernetes 上下文 `darkdev-microk8s`、命名空间 `tickety` 与 `kubectl --context darkdev-microk8s`；镜像使用 `localhost:32000/tickety-backend:<tag>` 与 `localhost:32000/tickety-frontend:<tag>`。
   - 必需行为：映射未出现冲突时直接使用上述可审计 CLI 通道，仅执行目标上下文、命名空间、当前构建与预期构建的快速门禁；不得重新遍历 DNS、Cloudflare、Azure、浏览器或无关集群做广泛 discovery。生产发布须在 `oci` 上执行 `scripts/verify-production-target.sh` 等价的全量静态资源门禁；跨主机传送镜像时仅使用受限回环隧道或既有私有通道，不得临时开放公网仓库。
   - 冲突处理：若固定上下文、命名空间、Ingress 或公网构建证据互相矛盾，停止发布并请求用户决定；不得自行改写固定映射。
   - 完成证据：两个固定目标的 Deployment 与 Pod 均就绪，各自公网域返回预期构建；其中 `https://tickety.situ.io` 还须通过生产全量资源门禁，且不得用 `tickety.imbell.com` 的结果替代。

3. 以让已验证环境知识散失为耻，以及时沉淀可复用规则为荣
   - 适用范围：工作中通过可审计证据确认或修正，且会影响后续执行的稳定环境事实，例如部署拓扑、目标主机、集群上下文、命名空间、节点架构、镜像通道、固定命令和验证门禁。
   - 必需行为：任务内及时使用 `codex-rule-refinery` 去重、审计，并把最小充分的稳定事实写入最近的项目 `AGENTS.md`；后续直接复用，事实变化时更新原规则并保留冲突与停止条件。
   - 禁止行为：不得让后续任务重复 discovery 同一稳定事实；不得把凭据、token、证书、Secret 值、临时 Pod/Job ID、一次性端口、短期指标或原始日志写入规则。
   - 放置边界：项目环境字面量只放项目 `AGENTS.md`；跨项目通用流程放相应技能，不得把项目事实提升为全局规则。
   - 完成证据：新增知识可被后续任务直接执行，来源覆盖与安装后验证通过，且规则不含敏感或瞬时数据。
