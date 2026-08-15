debate-protocol: 1
debate-scope: direct
debate-version: v0

# Tickety operating profiles: product and architecture recommendation

## Decision

Do not add more mutually exclusive “running modes.” The examples mix three different things: *watchdog* is an operational outcome, *on-demand* is a trigger, and *analytical* is a capability. A flat mode list would force combinations such as “on-demand manager analytics over a connected ITSM” into awkward or contradictory states.

Call the new user-facing concept **Operating Profiles**. Back profiles with orthogonal policy axes and allow several profiles to be enabled at once. Keep the terms already present in Tickety separate:

- **Environment:** `APP_MODE=demo|production` controls safety/configuration.
- **Ticket placement/binding:** standalone or an external provider adapter controls the system of record. Freshservice and Jira adapters exist in the inspected tree; ServiceNow does not yet exist and must not be implied.
- **Process topology:** `TICKETY_PROCESS_ROLE=api|worker|all` controls which process serves or schedules work.
- **Operating profile:** controls when Tickety evaluates work, for whom, at what scope, and with what authority.

This model works whether Tickety owns the tickets or complements an ITSM. A validated adapter capability manifest—not the profile name—determines what Tickety may read, receive, or change.

## Internal policy model

Each profile expands into a versioned policy with these independent axes:

1. **Trigger:** explicit request, supported inbound event, or periodic scan.
2. **Freshness class:** snapshot, periodic, or near-real-time with a measured SLO.
3. **Audience/surface:** manager, agent, or automation/API.
4. **Scope:** ticket, queue/team, or organization/systemic.
5. **Authority:** observe, recommend, prepare, or act.
6. **Guardrails:** tenant/binding, eligibility/privacy rules, budgets, allowed capabilities, approval rules, retention, and freshness threshold.

Profiles are presets over these axes, not separate code paths or AI personalities. “Analytics” is an output used by profiles. “On-demand” and “continuous” can coexist. “Orchestration” is the governed execution substrate and, later, an authority level—not a persona-facing peer to standalone/add-on placement.

## Recommended profiles

### 1. Manager Briefing — ship in MVP

- **Purpose/persona:** a helpdesk manager deliberately asks, “What needs my attention now?”
- **Trigger/freshness:** on-demand refresh; optionally reuse recent materialized results. Return `source_as_of`, `evaluated_at`, and `freshness` on every section.
- **Scope:** selected queue/team or organization, with ticket drill-down.
- **Outputs:** existing alerts, prioritized backlog, SLA exposure, trends, systemic clusters, workload, reporter health, routing suggestions, provenance/confidence, and a concise briefing.
- **Authority/side effects:** observe and recommend only. It may prepare a reviewable worklist, but cannot mutate a provider.
- **Human boundary:** a manager explicitly applies any follow-up through an authorized audited workflow.
- **Degraded behavior:** partial sections remain visibly partial; a recent snapshot may be shown with its age; otherwise show unavailable/retry. Never silently label stale data current.

This is the useful part of the user’s “on-demand mode,” but on-demand is the trigger and Manager Briefing is the outcome.

### 2. Agent Assist — ship in MVP

- **Purpose/persona:** analytical help inside the ticket an agent is already handling.
- **Trigger/freshness:** explicit per-ticket request or user-initiated refresh, using the current ticket version and bounded related context.
- **Scope:** one ticket, with only authorized related evidence.
- **Outputs:** triage, summary, suggested resolution/reply, streamed progress, provenance, artifact age, and eligibility explanation.
- **Authority/side effects:** observe and recommend; a generated reply or plan is a draft, not a sent action.
- **Human boundary:** the agent reviews/edits and explicitly submits through a separately authorized existing flow.
- **Degraded behavior:** use a valid cached artifact with its age or show timeout, rate-limit, or unavailable state. Never fabricate a fallback result and never silently write externally.

This captures the user’s “agent analytical mode” without treating analysis as a deployment state or permitting ambient scanning of external/portal tickets.

### 3. Continuous Watch — ship after the read-only MVP

- **Purpose/persona:** governed proactive oversight for managers, with agent notifications where authorized.
- **Trigger/freshness:** periodic scans plus authenticated, supported inbound provider events. Call it **continuous**, not realtime, at launch. Use **near-real-time** only for a documented event path after measuring an accepted-event-to-finding SLO. Polling is periodic regardless of interval.
- **Scope:** configured queues/teams and ticket classes; organization-level pattern detection may run less frequently.
- **Outputs:** deduplicated alerts, SLA/risk/workload watchlists, systemic signals, notifications, and recommended responses.
- **Authority/side effects:** ambient observe/recommend is allowed. It may later create an immutable proposed action for review. `act` is disabled initially.
- **Human boundary:** a designated manager approves prepared changes in early action phases. Generated escalation remains a suggestion until a human applies it.
- **Degraded behavior:** invalid/replayed/ambiguous events are rejected or quarantined. Provider outage, missed scans, stale data, budget exhaustion, or circuit opening pauses affected evaluation, preserves visibly stale last-known results, and performs no external action.

This replaces the ambiguous “realtime watchdog mode.” Watchdog is directionally useful, but “Continuous Watch” is more accurate and less likely to imply infallible realtime coverage.

### Later capability: Guarded Orchestration, not an MVP mode

When Tickety has a durable executor and narrowly proven connector actions, an administrator may allow a profile to move from `recommend` to `prepare`, then to `act`. This is a policy promotion, not a fourth exclusive runtime mode. Any external action requires all of the following at decision time and execution time:

- supported and currently validated adapter capability;
- tenant, binding, resource, and actor identity;
- RBAC plus an explicit allow-listed action policy;
- immutable policy decision and evidence record;
- human approval in early phases;
- idempotency key and confirmed provider receipt;
- retry semantics appropriate to that provider action;
- global, tenant, binding, profile, and external-write kill switches;
- reversal/compensation only where the adapter explicitly supports an audited safe reversal.

Irreversible autonomous changes remain out of scope pending a separate trust-and-safety decision.

## Composition and conflict resolution

Profiles may run concurrently. A tenant can use Agent Assist on a ticket, ask for a Manager Briefing, and have Continuous Watch observe the same queue.

Resolve an execution against one effective policy. The following rules are mandatory:

- A deny, disabled profile, failed eligibility/privacy check, missing capability, stale binding, exhausted budget, or open circuit wins over an allow.
- No profile increases a user’s RBAC or an adapter’s capability.
- Select the narrowest authorized data scope and the least authority necessary.
- Deduplicate findings by tenant, binding, resource/version, finding type, and policy version; coalesce repeated signals without losing evidence.
- Deduplicate events/actions with stable idempotency keys. Multiple profiles may contribute evidence to one finding but may not issue competing writes.
- Read-only profiles never resolve a business conflict automatically. Conflicting proposed actions require human resolution.

## Execution architecture

### MVP: reuse first, add only policy and durable result state

- Keep API replicas responsible for explicit ticket analysis, briefing refresh requests, profile administration/preview, queries, and approvals.
- Keep the dedicated worker and APScheduler for existing fixed-interval sync/AI work and bounded profile scans.
- Introduce one shared **PolicyEvaluator** used by scheduled and on-demand paths. It calls existing intelligence/AI services and preserves current eligibility checks, strict AI contracts, leases, budgets, cache identity, timeouts/retries, provenance, and retention.
- Reuse adapter capability manifests during profile validation and again before an action. Unsupported capabilities are disabled with a reason; never emulate missing parity.
- Reuse WebSockets only to project persisted analysis/run/notification state to users. A socket connection is not a durable event source or source of truth.
- Preserve signed webhook handling. In the MVP, a supported webhook may trigger bounded evaluation only if the existing handler can atomically deduplicate the delivery and persist the resulting run/finding state. Do not build a general event bus merely to power the first read-only profiles.

Minimum new primitives:

- `ProfileDefinition`: preset/type, policy JSON, version, owner, enabled state.
- `ProfileBinding`: tenant/binding and queue/team scope, schedule/event eligibility, budgets.
- `ProfileRun`: trigger, input watermark/version, status, freshness, counts, timestamps, failure code.
- `Finding`: evidence/provenance, severity, dedupe key, lifecycle, source/evaluation timestamps.
- `ProposedAction`: only when `prepare` is introduced; requested capability, policy decision, approval state, idempotency key, provider receipt.

Minimum API surface:

- list/create/update/enable profiles and preview the effective policy;
- trigger and read a Manager Briefing/profile run;
- inspect run/finding status and freshness;
- acknowledge/snooze/resolve a finding;
- later, approve/reject a proposed action and inspect capability/execution receipts.

Existing on-demand ticket, intelligence, sync, webhook, and maintenance routes stay compatible; internal refactoring behind those contracts should be feature-flagged.

### When APScheduler becomes insufficient

APScheduler is acceptable for a bounded scan-based MVP but is not a durable orchestration system. Add a Postgres outbox/event/job ledger and resumable worker processing—or choose a workflow technology later—when measured requirements show one or more of:

- accepted events or requested work can be lost across process/database failure;
- required recovery, per-tenant fairness, queue depth, or event volume cannot be met;
- long-running/multi-step workflows need persisted state and resumability;
- retries, dead-letter handling, ordering, or backpressure cannot be represented safely;
- a published freshness SLO is missed because of scheduler/polling behavior;
- approval-gated external actions need an atomic decision-to-execution record.

The durable layer normalizes a minimal `EventEnvelope`: event ID, tenant, binding/provider, resource ID/version, event type, source/received time, validation status, payload reference/hash, correlation key, and idempotency key. Persist minimized/redacted references rather than unnecessary raw ticket content. Do not claim providers emit events unless their validated capability and implementation support them.

## Compatibility and migration

- Standalone versus provider-backed placement remains unchanged and independent of profiles.
- `APP_MODE` and `TICKETY_PROCESS_ROLE` remain unchanged. Production keeps scaled API replicas separate from its worker; demo may retain `all` under current safety rules.
- Existing manual sync/fetch, bulk queue/repair, signed webhook, scheduled scan, and per-ticket analysis routes continue working.
- Current `AUTO_*` toggles remain authoritative during migration. Map each one to a previewed default policy only after inventorying its exact semantics. Start with dual-observe comparison; do not delete toggles until equivalence, default-off behavior, eligibility, rollback, and administrator opt-in are verified.
- Existing deployments get safe defaults that expose current on-demand behavior but do not enable new ambient AI or provider writes.
- External/portal text remains untrusted. Preserve the current rule that it is not implicitly swept into AI processing merely because transport authentication succeeded; explicit authenticated eligibility is still required.

## Operational, security, and failure controls

- Scope every profile, event, run, finding, cache key, lease, and action by tenant and binding. Test cross-tenant and cross-binding isolation at every boundary.
- Separate profile administration, manager review/approval, agent ticket access, and external-write permission in RBAC.
- Audit profile/version changes, effective policy resolution, eligibility decisions, evidence/provenance, run lifecycle, finding state, approvals/rejections, action attempts/receipts, and operator overrides.
- Apply per-tenant/profile/provider token/request/cost budgets, concurrency limits, queue limits, circuit breakers, bounded retries with backoff, quarantine/dead-letter states, and load shedding. Never create an ambient LLM loop.
- Do not retry a non-idempotent provider write unless the adapter contract and recorded state make the result unambiguous.
- Track queue/scan lag, accepted-event-to-finding latency, snapshot age, stale percentage, duplicates suppressed, finding acknowledgement/resolution, false-positive/alert-noise feedback, failure reasons, budget use, approval outcomes, and connector capability failures.
- Detect replay, spoofed, duplicate, and out-of-order webhooks; validate signatures/timestamps, store delivery identity, use provider resource versions where available, and quarantine ambiguity.

Pause or stop a profile when binding authorization/capability is invalid, authenticity or tenant isolation cannot be proven, input is older than its policy permits, AI eligibility fails, the budget/circuit/queue threshold trips, duplicate/action state is ambiguous, required approval is absent, or provider success cannot be confirmed safely.

Rollback is policy-first: disable the new profile/version, stop unstarted work and retries, retain read-only audit evidence, and restore the last known safe version or legacy route/toggle behavior. Never perform speculative compensation against an external ITSM.

## Delivery sequence and validation

### Phase 1 — read-only/recommendation MVP

Ship terminology/policy schema, Manager Briefing, and Agent Assist. Add freshness labels, run state, policy preview, capability-aware UI/API, audit/metrics, feature flags, and kill switches while reusing existing endpoints and worker.

Validate:

- current-route and `AUTO_*` behavior remains equivalent when profiles are disabled;
- RBAC and tenant/binding isolation fail closed;
- external/portal AI eligibility is unchanged;
- stale/partial/unavailable states are truthful;
- budgets and cached artifacts behave as designed;
- there is no new external-write path;
- managers and agents complete representative tasks more effectively in user testing.

### Phase 2 — Continuous Watch

Add scheduled policy evaluation, supported signed-webhook triggers, durable findings, deduplication, acknowledgements/snoozes, notification rules, run health, and prepared-but-not-executed action records. If direct webhook-to-run persistence cannot meet recovery needs, introduce the Postgres outbox/job ledger here.

Validate duplicate, replayed, delayed and out-of-order events; process/database restart and missed scans; provider outage; quota exhaustion; scan lag/freshness; alert volume and false-positive tolerance; and kill-switch/rollback drills.

### Phase 3 — durable guarded orchestration

Only if Phase 2 evidence crosses the APScheduler insufficiency conditions, add durable event/job state, resumable workflows, tenant-fair claiming, explicit retry/dead-letter/backpressure behavior, and approval-gated connector actions. Vendor selection remains a separate decision.

### Phase 4 — narrow external actions and new adapters

Enable only explicitly supported, preferably reversible actions after separate security review and pilot evidence. ServiceNow is a separate adapter/capability project; its future presence does not change the profile model.

## Option ledger

- **Flat mutually exclusive mode list:** reject. It conflates trigger, persona, scope, and authority and grows combinatorially.
- **Independent policy axes only:** retain as the internal model, but not the primary UX; customers need outcome-oriented presets.
- **Full durable event orchestration now:** defer. It is a likely later substrate, but building it before profile value, load, recovery, action, and SLO requirements are known delays useful read-only capabilities.
- **Separate narrow watchdog service:** reject initially. Continuous Watch should reuse governed worker/policy infrastructure; extract only if measured isolation or scaling needs justify it.
- **Query-only on-demand intelligence:** retain inside Manager Briefing and Agent Assist, but it cannot provide proactive oversight alone.
- **Named AI agents/general multi-agent framework:** reject as the primary abstraction. It obscures trigger, data, authority, budgets, and connector contracts; bounded AI services fit Tickety’s current controls.
- **Policy axes + opinionated profiles + incremental executor:** choose. It provides clear UX now and a path to durable orchestration without false capability claims.

## Retained unknowns

- Which profile customers value first and how much alert noise they will tolerate.
- Exact manager freshness/SLO targets, scale, event volume, recovery objectives, and failure budget.
- Customer tenant, queue/team, RBAC, delegation, and approval models.
- Data residency, retention, provider-processing, and private-comment policies per tenant.
- Which provider events carry stable IDs/resource versions and what each adapter can truly read or write.
- Which actions customers consider safe/reversible and whether providers offer usable idempotency/reversal contracts.
- Exact inventory and migration semantics of every current `AUTO_*` toggle.
- Whether the present worker and database behavior meet pilot fairness/recovery needs.
- Pricing/packaging and detailed UI language, which require product research.

## Out of scope

No code change, provider/workflow vendor selection, detailed UI mockup, pricing, ServiceNow implementation, unsupported provider parity, exact unmeasured SLO/cost promise, or autonomous irreversible action is approved by this recommendation.

## Acceptance coverage

The design explicitly corrects the user’s examples; separates persona, cadence, scope, and authority; allows profiles to compose; gives managers deliberate and continuous oversight plus agents in-context help; constrains realtime claims to measured event paths; retains human control and adapter capability gates; fits current APIs/worker/controls; identifies the durable-executor threshold; provides migration, failure, rollback, and stop behavior; sequences value before platform work; and states assumptions and unknowns without claiming ServiceNow or write parity.
