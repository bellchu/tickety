import type { ResolverGroup } from "./types";

export const resolverGroupCatalog: ReadonlyArray<{
  code: ResolverGroup;
  label: string;
  domain: "Infrastructure" | "Applications";
  description: string;
}> = [
  { code: "INFRA_HELPDESK", label: "Helpdesk", domain: "Infrastructure", description: "Endpoint, basic access, setup, and first-line triage." },
  { code: "INFRA_NETWORK", label: "Network", domain: "Infrastructure", description: "Shared connectivity, routing, DNS, firewall, and network paths." },
  { code: "INFRA_SYSTEMS", label: "Systems", domain: "Infrastructure", description: "Servers, VMs, identity platform, storage, certificates, and backups." },
  { code: "INFRA_ARCH", label: "Architecture", domain: "Infrastructure", description: "Explicit solution design, standards, and technical architecture." },
  { code: "APP_CRM_ALMO", label: "CRM · ALMO", domain: "Applications", description: "CRM application behavior in the ALMO business context." },
  { code: "APP_CRM_JAM", label: "CRM · JAM", domain: "Applications", description: "CRM application behavior in the JAM business context." },
  { code: "APP_RPA", label: "RPA", domain: "Applications", description: "Automation workflows, bot execution, scheduling, and orchestration." },
  { code: "APP_SQL", label: "SQL", domain: "Applications", description: "Queries, procedures, database objects, and data-layer logic." },
  { code: "APP_JDE", label: "JDE technical", domain: "Applications", description: "JDE application errors, services, batches, and technical processing." },
  { code: "APP_JDE_BA", label: "JDE functional", domain: "Applications", description: "JDE workflow, setup, business rules, and transaction behavior." },
  { code: "APP_KORBER", label: "Korber / WMS", domain: "Applications", description: "Korber and warehouse-management application behavior." },
  { code: "APP_AS400", label: "IBM i / AS400", domain: "Applications", description: "IBM i jobs, queues, processing, and legacy application behavior." },
  { code: "APP_WEB", label: "Web applications", domain: "Applications", description: "Supported web-application functionality and web-layer defects." },
  { code: "APP_EDI_API", label: "EDI / API", domain: "Applications", description: "Interfaces, middleware, transformation, mapping, and delivery." },
  { code: "APP_PM", label: "Project management", domain: "Applications", description: "Explicit project planning, coordination, and status work." },
];

export const resolverGroupByCode = new Map(
  resolverGroupCatalog.map((item) => [item.code, item]),
);
