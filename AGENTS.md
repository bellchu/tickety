# Tickety project rules

1. 以将其他域名误认为生产环境为耻，以将 `tickety.nexora.com` 作为唯一指定生产环境为荣
   - 适用范围：所有生产部署、发布验证、监控、链接与部署文档。
   - 必需行为：生产部署与验证必须以 `https://tickety.nexora.com` 为目标；执行前通过项目现有的可审计 CLI、API 或基础设施即代码流程确认其后端目标。
   - 禁止行为：不得将任何其他域名当作生产环境，也不得用其健康状态或页面结果替代生产验证。
   - 完成证据：部署后须在 `https://tickety.nexora.com` 验证就绪状态和预期构建版本，并保留可审计的命令、差异或响应证据。

2. 以每次重新猜测部署目标为耻，以复用固定目标映射为荣
   - 固定生产映射：`https://tickety.nexora.com` 通过 Cloudflare Tunnel 转发到本机 `https://localhost:443`，由 Compose `tunnel-proxy` 转发到 `frontend:3000`。
   - 必需行为：使用 `docker compose` 构建和发布，并在发布前后验证 Compose 配置、服务健康、公网就绪状态与预期 Git 提交的构建元数据。
   - 冲突处理：若 Compose、Cloudflare Tunnel 或公网构建证据互相矛盾，停止发布并请求用户决定；不得自行改写固定映射。
   - 完成证据：所有 Compose 服务均就绪，`https://tickety.nexora.com` 返回就绪状态与预期构建。
