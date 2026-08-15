# Canonical debate brief: Tickety operating profiles

## Destination and requested output

Produce one opinionated product and technical architecture recommendation for expanding Tickety beyond its current ticket-system placement choices (standalone versus connected/embedded with an external ITSM). The output must explain whether Tickety should have additional "running modes," what they should be called, how they compose, which should ship first, and how the existing codebase can evolve safely. This is a design recommendation only; do not implement code.

## User intent

The user wants Tickety to support operational experiences such as continuous/realtime watchdog oversight, on-demand manager review, and agent-facing analysis, but explicitly says those examples may not be ideal and requests critical alternatives and opinions. Tickety should eventually complement systems such as Freshservice and ServiceNow as well as run standalone.

## Observed repository facts (local source inspection)

- Tickety is a Python/FastAPI + PostgreSQL backend and Next.js frontend. AI calls use strict output contracts, cached artifacts, database leases, concurrency/rate/token budgets, timeout/retry controls, and provenance/retention controls.
- Three separate concepts already use mode-like terminology:
  - application safety environment: `APP_MODE=demo|production`;
  - ticket-system placement/provider: standalone, Freshservice, or Jira through an adapter registry (ServiceNow is not implemented in the inspected tree);
  - process topology: `TICKETY_PROCESS_ROLE=api|worker|all`.
- Production separates HTTP API replicas from one dedicated background worker. The worker uses APScheduler and currently owns two fixed interval jobs: external synchronization and automatic AI gap filling/triage. It is not yet a general durable orchestration engine.
- The product already supports several trigger paths: scheduled sync/AI scans, signed external webhooks, explicit per-ticket analysis routes, manual admin sync/fetch, and bulk queue/repair routes.
- Existing manager intelligence APIs include alerts, prioritization, SLA status, trends, systemic issues, workload, reporter health, and routing. Protected intelligence is limited to administrator/supervisor roles. Agent-facing ticket AI includes triage, summary, suggested resolution/reply, and a ticket analysis stream.
- WebSockets exist for ticket analysis progress and notifications. This does not by itself prove durable low-latency event processing or a true realtime system.
- External/portal content has stronger safety restrictions: implicit AI gap scanning is limited to Tickety-owned tickets; external and portal tickets need an explicitly authenticated workflow to queue AI. Generated escalation decisions remain suggestions until a human applies an audited action.
- External integration capabilities are intentionally explicit and incomplete. Freshservice read/sync/webhook support exists; guarded status/priority write-back exists but remains subject to identity/capability gates, and replies, private notes, attachments, and service-request parity are not claimed. No ServiceNow adapter is present in the inspected tree.
- The working tree contains extensive user changes. The recommendation must not assume unfinished code is already released and must not require modifying it.

## Terminology constraint

Avoid overloading `APP_MODE`, ITSM provider/placement, or process role. Decide whether the new concept should instead be called an operating profile, engagement profile, automation policy, orchestration policy, or another precise term. Distinguish user-facing presets from orthogonal technical controls.

## Material option families to evaluate

1. A flat mutually exclusive list of new running modes (for example watchdog, on-demand, analytical).
2. Independent policy axes with user-facing presets. Candidate axes include trigger (`event`, `continuous/scheduled`, `on-demand`), audience/surface (`manager`, `agent`, `automation/API`), authority (`observe`, `recommend`, `prepare`, `act`), and scope (`ticket`, `queue/team`, `organization/systemic`).
3. A durable event-driven orchestration platform now: normalized events, job queue/workflow state, retries/idempotency, policy evaluation, and connector actions.
4. A narrow always-on watchdog service layered over the existing APScheduler worker.
5. Query-only on-demand intelligence snapshots, with no ambient processing.
6. Named AI-agent roles or a general multi-agent framework as the primary abstraction.
7. A relevant hybrid: policy axes as the domain model, a few opinionated UX presets, and an incremental executor that initially reuses existing endpoints/worker but later gains a durable event/job layer.

Do not treat cosmetic naming permutations as separate architectures. Retain or prune each option with rationale.

## Required design detail

The recommendation must include:

- a clean conceptual model separating deployment/placement, process topology, trigger/freshness, audience, scope, and automation authority;
- a small recommended set of user-facing profiles, with names and exact behaviors;
- for each profile: trigger, freshness expectation, data scope, outputs, permitted side effects, human approval boundary, primary persona, and failure/degraded behavior;
- whether profiles can run concurrently and how policy conflicts are resolved;
- an execution architecture that reuses current APIs, adapter capability manifests, AI leases/budgets/cache/provenance, webhooks, scheduled worker, and WebSockets where appropriate;
- the minimum new primitives/data model/API surface required, without inventing provider capabilities;
- compatibility/migration for current standalone/external provider selection, demo/production, `api|worker|all`, current `AUTO_*` toggles, and existing on-demand routes;
- observability, audit, tenant/binding isolation, RBAC, privacy, cost controls, idempotency, backpressure, stale-data labeling, rollback/kill switches, and stop conditions;
- a staged delivery plan with explicit MVP, later phases, validation criteria, and what not to build yet;
- retained unknowns requiring user research or implementation discovery.

## Acceptance criteria

1. Reject or accept the user's example modes with explicit reasoning rather than merely renaming them.
2. Avoid a combinatorial or mutually exclusive mode design when capabilities should compose.
3. Give managers a deliberate oversight experience and agents an in-context analytical experience without conflating persona with trigger cadence.
4. Use "realtime" only if backed by an explicit event path and measurable freshness SLO; otherwise use accurate language such as continuous or near-real-time.
5. Preserve human control: read-only observation and recommendations may be ambient, but external write actions require explicit capability, authorization, policy, audit, idempotency, and preferably approval in early phases.
6. Fit the observed Tickety architecture and identify when APScheduler is insufficient.
7. Recommend a credible sequence that delivers user value before a general-purpose orchestration engine.
8. Include failure, degraded, rollback, and stop conditions, not only the happy path.
9. State assumptions and retained unknowns; do not claim ServiceNow or external write parity exists.
10. Be concise enough to act on while detailed enough to guide product and architecture decisions.

## Explicit constraints and assumptions

- No repository or production changes are authorized in this debate.
- Prefer existing interfaces and controls over speculative new abstractions.
- Treat external ticket text as untrusted and do not weaken current AI eligibility/privacy restrictions.
- The solution should work in standalone and external-provider placements; availability of individual actions must be derived from the selected adapter's validated capabilities.
- Assume supervisors/managers and agents are distinct personas, but exact customer RBAC and tenancy requirements remain to be validated.
- Assume "realtime" means prompt reaction to supported inbound events, not continuous LLM calls or constant polling.

## Out of scope

- Implementing ServiceNow, provider-specific parity, or code changes.
- Choosing a workflow/queue vendor.
- Detailed UI mockups, pricing, packaging, or licensing.
- Autonomous irreversible changes without a separately approved trust and safety design.
- Claiming exact scale, latency, or cost targets before product requirements and load measurements exist.

## Required voting checklist

Both voters must cover acceptance requirements, all material options and hybrids, implementation detail, compatibility, failure paths, rollback, stop conditions, retained unknowns, scope exclusions, risks, and adversarial checks. Proposal verdict must be `PROPOSE`. Review may approve only if the exact candidate fully covers the brief.
