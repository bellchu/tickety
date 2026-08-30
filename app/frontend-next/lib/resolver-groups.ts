import type { ResolverGroup } from "./types";

export const resolverGroupCatalog: ReadonlyArray<{
  code: ResolverGroup;
  label: string;
  domain: "Infrastructure" | "Applications";
  description: string;
}> = [
  { code: "SERVICE_DESK", label: "Service desk", domain: "Infrastructure", description: "First-line intake, triage, common requests, and ownership coordination." },
  { code: "ENDPOINT_SUPPORT", label: "Endpoint support", domain: "Infrastructure", description: "User devices, operating systems, peripherals, and managed workstation software." },
  { code: "IDENTITY_ACCESS", label: "Identity & access", domain: "Infrastructure", description: "Accounts, authentication, authorization, access requests, and directory services." },
  { code: "NETWORK_OPERATIONS", label: "Network operations", domain: "Infrastructure", description: "Connectivity, routing, DNS, firewall, VPN, and shared network services." },
  { code: "INFRASTRUCTURE_OPERATIONS", label: "Infrastructure operations", domain: "Infrastructure", description: "Compute, operating platforms, storage, backup, certificates, and availability." },
  { code: "CLOUD_PLATFORM", label: "Cloud platform", domain: "Infrastructure", description: "Cloud services, orchestration, platform engineering, and shared runtime foundations." },
  { code: "SECURITY_OPERATIONS", label: "Security operations", domain: "Infrastructure", description: "Security events, vulnerabilities, policy enforcement, and incident response." },
  { code: "BUSINESS_APPLICATIONS", label: "Business applications", domain: "Applications", description: "Business workflows, application configuration, and functional support." },
  { code: "APPLICATION_OPERATIONS", label: "Application operations", domain: "Applications", description: "Application availability, runtime failures, jobs, queues, and technical support." },
  { code: "DATA_SERVICES", label: "Data services", domain: "Applications", description: "Databases, queries, data pipelines, reporting, and data-platform operations." },
  { code: "INTEGRATION_SERVICES", label: "Integration services", domain: "Applications", description: "APIs, messaging, middleware, transformation, and system-to-system delivery." },
  { code: "AUTOMATION_SERVICES", label: "Automation services", domain: "Applications", description: "Workflow automation, scheduled execution, bots, and orchestration." },
  { code: "SOFTWARE_ENGINEERING", label: "Software engineering", domain: "Applications", description: "Product defects, code-level investigation, builds, and release remediation." },
  { code: "SERVICE_DELIVERY", label: "Service delivery", domain: "Applications", description: "Service ownership, coordinated delivery, planning, and cross-team follow-through." },
];

export const resolverGroupByCode = new Map(
  resolverGroupCatalog.map((item) => [item.code, item]),
);
