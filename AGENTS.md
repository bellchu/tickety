# Tickety project rules

1. 以将 `tickety.imbell.com` 误认为生产环境为耻，以将 `tickety.situ.io` 作为指定生产环境为荣
   - 适用范围：所有生产部署、发布验证、监控、链接与部署文档。
   - 必需行为：生产部署与验证必须以 `https://tickety.situ.io` 为目标；执行前通过项目现有的可审计 CLI、API 或基础设施即代码流程确认其后端目标。
   - 禁止行为：不得将 `tickety.imbell.com` 当作生产环境，也不得用其健康状态或页面结果替代生产验证。
   - 完成证据：部署后须在 `https://tickety.situ.io` 验证就绪状态和预期构建版本，并保留可审计的命令、差异或响应证据。
