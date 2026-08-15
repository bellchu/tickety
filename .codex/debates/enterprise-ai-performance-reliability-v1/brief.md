# Canonical debate brief: enterprise AI/LLM performance and reliability

## Destination

Produce one implementation-ready architecture recommendation for improving Tickety's AI/LLM performance and reliability for an enterprise deployment with approximately 300–400 ITSM users. The recommendation must be proportionate to this scale, preserve existing security boundaries, and distinguish immediate hardening from optional scale-triggered additions.

## Requested output

Return a concise but implementation-ready decision artifact containing:

1. the recommended target architecture and why it wins;
2. a request/job lifecycle with failure and recovery behavior;
3. initial capacity assumptions and configuration for 300–400 users;
4. measurable SLOs, dashboards, alerts, and load/failure test gates;
5. a phased rollout with rollback and stop conditions;
6. an option ledger showing what is retained, deferred, or rejected; and
7. explicit retained unknowns and the measurements needed to resolve them.

The artifact should make a clear decision rather than list generic best practices. It may use compact tables and pseudocode, but no diagram is required.

## Observed facts and source quality

The following facts were read directly from the current Tickety repository and are high-quality implementation evidence:

- The backend is FastAPI with SQLAlchemy/Alembic and PostgreSQL/pgvector. Production deployment already separates `api` and `worker` process roles.
- The Helm chart defaults to one backend replica and one worker replica. The worker replica count is fixed at one and uses an APScheduler loop with `max_instances=1`.
- The AI sweep polls every 30 seconds, fetches small bounded batches, and then runs ticket work serially through repeated `asyncio.run` calls. Ticket columns hold queue-like state: status, claim ID, lease expiry, attempt count, next attempt, error, and requested artifacts.
- Ticket analysis already uses cross-process atomic claims, expiring leases, retry scheduling, dead-letter state, input hashes, pipeline/model provenance, and exact artifact reuse when source/model/pipeline identity is unchanged.
- A complete ticket pipeline can run triage, summary, route, and resolution; LLM-dependent artifacts are mostly sequential because later prompts depend on earlier outputs. The configured pipeline deadline defaults to 900 seconds.
- Interactive endpoints can execute LLM work in the API request or WebSocket lifecycle, so provider latency can consume API capacity and a client disconnect can complicate user-visible recovery.
- `LLMManager` calls a single resolved provider/model for a request. It enforces structured output, prompt/output bounds, per-attempt timeout, overall deadline, up to three same-provider retries with jitter and `Retry-After`, process-local semaphores, database-backed provider concurrency leases, shared RPM/TPM/daily-token admission, durable call metrics, secret redaction, and safe error classes.
- There is no explicit cross-provider circuit breaker, task-aware primary/secondary routing policy, or durable per-artifact `ai_jobs` table.
- The API exposes liveness/readiness and the deployment has rolling-update safety, but no HPA, PodDisruptionBudget, topology spread, or worker autoscaling is defined.
- The current dependency set has no Redis, RabbitMQ, Kafka, Celery, or managed queue client.

The only workload fact supplied by the user is approximately 300–400 ITSM users. No measured concurrency, ticket-arrival distribution, provider quotas, data residency constraint, recovery objective, SLA, or monthly model budget was supplied. Any numerical starting point must therefore be labeled as a bootstrap load-test assumption, not an observed production fact.

## Constraints and assumptions

- Preserve existing authorization, prompt-containment, secret-redaction, provider-host validation, source provenance, quotas, and production fail-closed behavior.
- Do not make the core ITSM application unavailable merely because an LLM provider is slow or down. AI may degrade while ticketing remains healthy.
- Prefer reversible evolution over a rewrite. Reuse PostgreSQL, existing claim/provenance records, and the deployed API/worker split where sound.
- Treat external model calls as at-least-once side effects: timeouts may still be billed or complete remotely. Final database effects must be idempotent and stale results must not overwrite newer ticket state.
- Keep customer/ticket data within approved provider and region boundaries. A fallback provider may be used only if independently approved for the same data classification and residency.
- Do not promise exactly-once execution. Require at-least-once job delivery with idempotent result commitment.
- Capacity must be driven by measured peak AI demand and provider RPM/TPM, not by total licensed user count alone.
- The design should operate initially on PostgreSQL without introducing an infrastructure dependency unless the benefit is material at this scale.
- Human approval remains required for high-impact actions; this decision concerns analysis, suggestions, summaries, routing recommendations, and retrieval, not autonomous destructive remediation.

## Acceptance requirements

The final candidate must satisfy all of the following:

1. **Responsive UX:** long LLM work does not hold scarce API execution capacity. An accepted interactive AI request returns a durable job identity within a target p95 of 1 second, and progress/result retrieval survives refresh, reconnect, API restart, and worker restart.
2. **Durable processing:** accepted work is not lost on process termination. Claims expire, retries use bounded exponential backoff with jitter, poison work reaches a queryable dead-letter state, and commits reject stale input, lost leases, or duplicate completion.
3. **Controlled concurrency:** global, provider, model, task, and tenant/user admission prevents provider 429 storms and noisy-neighbor starvation. Interactive work has bounded preference over background/backfill work without starving it.
4. **Provider resilience:** the design distinguishes retryable transport/rate failures, invalid model output, permanent configuration/auth failures, and policy/data-residency blocks. It includes circuit breaking and an approved fallback policy without retry multiplication.
5. **Performance efficiency:** exact-result reuse and prompt/token reduction are retained. Expensive semantic caching of final ticket decisions must not be assumed safe; any cache proposal needs explicit correctness boundaries.
6. **Proportionate topology:** provide a sensible initial deployment for 300–400 users and explicit evidence-based triggers for adding Redis/managed queue, more workers, more providers, or self-hosted inference.
7. **Quantitative verification:** define bootstrap workload assumptions, SLOs, provider-independent and end-to-end metrics, alerts, a load-test matrix, failure injection, and pass/fail gates before broad rollout.
8. **Operational safety:** specify rollout phases, database migration compatibility, feature flags, rollback, draining, replay/requeue procedure, stop conditions, and operator runbooks.
9. **Cost/security:** token and request budgets remain enforced across replicas; observability avoids raw ticket content and secrets; fallback never crosses an unapproved trust boundary.
10. **Complete option ledger:** consider all option families below and relevant hybrids, with feasibility, dependencies, benefits, costs, risks, unknowns, and retain/prune rationale.

## Material option families

### Option A — Tune the current single scheduler/worker and synchronous API paths

- **Feasibility/evidence:** highest reuse and smallest code change. Existing bounded batches, leases, retries, exact artifact cache, quotas, and metrics are useful foundations.
- **Benefits:** fastest delivery, no new infrastructure, low operating burden.
- **Costs/risks:** the serial polling loop and one fixed worker constrain throughput; 30-second polling adds queue latency; synchronous API/WebSocket execution still couples app health to provider latency; single-worker maintenance causes backlog; scaling APScheduler replicas risks duplicated scans even if claims limit duplicate commits.
- **Dependencies:** configuration tuning, better indexes, perhaps lower poll interval, and more explicit metrics.
- **Unknowns:** may be sufficient if actual demand is very low, but cannot be assumed for 300–400 users without load evidence.
- **Retain/prune question:** retain as immediate hardening only, or accept as the target architecture?

### Option B — PostgreSQL-backed durable `ai_jobs` queue with scalable async workers

- **Feasibility/evidence:** PostgreSQL and ticket claim fields already exist. Add a normalized per-artifact job table and claim with `FOR UPDATE SKIP LOCKED`, leases, heartbeats, `not_before`, priority, attempts, idempotency key, input hash, and result reference. API returns `202` plus job ID; clients use resumable polling/SSE/WebSocket progress. Run multiple worker replicas with bounded asynchronous concurrency.
- **Benefits:** removes long LLM work from API requests; no new datastore; durable and inspectable; horizontal worker scale; explicit fairness, retry, DLQ, and backlog metrics; good fit for modest enterprise scale.
- **Costs/risks:** PostgreSQL polling and queue indexes add load; lease/idempotency correctness requires care; notifications still need polling or a wake-up mechanism; schema and worker orchestration are meaningful changes.
- **Dependencies:** new migration/table/indexes; worker loop separate from APScheduler; idempotent artifact commit; job/status API; compatibility bridge from ticket queue fields.
- **Unknowns:** peak queue throughput and database headroom.
- **Retain/prune question:** target architecture, interim step, or insufficient without a broker?

### Option C — Dedicated broker/managed queue plus scalable workers

- **Feasibility/evidence:** standard durable-queue pattern, but no broker exists in the current stack. Candidates include Redis Streams, RabbitMQ, SQS/Azure Service Bus/Pub/Sub, or a workflow service.
- **Benefits:** efficient wake-up, high throughput, mature redelivery/DLQ, decoupled scaling, and potentially simpler autoscaling from queue depth.
- **Costs/risks:** adds an availability/security/backup dependency, operational skill, network policy, reconciliation between broker and PostgreSQL, and possible dual-write failure. Redis list/pubsub alone is not sufficient durability.
- **Dependencies:** product/cloud choice, data-residency approval, outbox pattern, broker client, operations ownership.
- **Unknowns:** hosting platform and whether measured load exceeds PostgreSQL queue capability.
- **Retain/prune question:** introduce now, use a transactional outbox hybrid, or defer behind measured triggers?

### Option D — Provider/model gateway with task-aware routing, circuit breakers, and fallback

- **Feasibility/evidence:** the code already abstracts providers through LiteLLM but binds a manager to one provider/model. A policy layer can select task routes and preserve schema validation and shared quotas.
- **Benefits:** cheaper/faster model for routine classification; stronger model for complex resolution; regional secondary for outages; circuit breaking avoids retry storms; canary and shadow evaluation support safe changes.
- **Costs/risks:** routing complexity, quality variance, duplicate budgets, data-processing approvals, and increased observability/evaluation burden. Cross-provider fallback is forbidden when trust/residency is not equivalent.
- **Dependencies:** approved model registry, per-task quality eval set, failure classifier, shared circuit state, routing audit, budget partitions.
- **Unknowns:** which providers/models/regions are contractually available and their real latency/quality/cost.
- **Retain/prune question:** implement application-level policy now, buy a gateway, or defer multi-provider fallback?

### Option E — Self-host or reserve dedicated model inference

- **Feasibility/evidence:** technically possible through the custom-provider path, but the current repository has no GPU inference stack or model operations capability.
- **Benefits:** data control, predictable reserved capacity, potentially lower marginal cost at sustained high utilization.
- **Costs/risks:** GPU cost, model serving and patching, quality/safety evaluation, HA complexity, capacity fragmentation, and likely poor economics at this user count unless regulatory or utilization facts justify it.
- **Dependencies:** approved model, GPU platform, autoscaling/HA, security review, evaluation and incident ownership.
- **Unknowns:** utilization, residency constraints, internal ML operations capability.
- **Retain/prune question:** reject for now, retain only as regulatory contingency, or use for embeddings only?

### Relevant hybrids to assess

- B + D: PostgreSQL durable queue with scalable workers plus task-aware provider policy.
- B now, C later: transactional job/outbox schema first, broker introduced only after measured queue/database thresholds.
- A then B: immediate configuration/observability fixes followed by durable async migration.
- B + selective C: PostgreSQL remains system of record while `LISTEN/NOTIFY` or a managed queue wakes workers; correctness does not depend on notification delivery.
- D + E: hosted primary with self-hosted fallback, allowed only if equivalent quality, security, and operational readiness are proven.

## Bootstrap sizing assumptions to challenge

Because no production trace exists, assess whether the following are safe initial test assumptions rather than capacity promises:

- 400 named users; 80 concurrent interactive sessions at peak.
- 30 interactive AI job submissions per minute sustained for 15 minutes, with a burst of 60 in one minute.
- Each full ticket analysis generates up to three external LLM calls because route is local and exact artifact reuse may eliminate work; individual artifact requests generate one call.
- 20 concurrent provider calls only if contracted quotas and token estimates permit; otherwise admission lowers concurrency.
- A background backlog of 1,000 ticket jobs must remain responsive to new interactive work and drain without data loss.
- Start with 2 API replicas across failure domains and 2–3 AI worker replicas, each with process concurrency 4, but enforce a lower shared provider limit until measurements justify more.

The final candidate may change these values, but must label all unmeasured numbers and provide formulas or load tests to replace them.

## Candidate SLOs to challenge

- Core ticketing API monthly availability: at least 99.9%, independent of LLM-provider health.
- AI job admission: p95 under 1 second and p99 under 2 seconds.
- Interactive AI: p95 queue wait under 2 seconds during normal load; p95 completion under 20 seconds for one-artifact tasks and under 60 seconds for a full pipeline, measured separately from backlog work.
- Reliability: at least 99.5% of accepted eligible AI jobs reach a valid terminal success within 5 minutes, excluding explicit policy/budget rejection; zero accepted jobs silently lost.
- Backlog recovery: after a 15-minute provider outage at the bootstrap load, interactive SLO recovers within 10 minutes and accumulated background work drains within 60 minutes without exceeding approved quotas.
- Quality remains at or above the accepted baseline for each task/model route; performance gains may not be purchased by silent structured-output or accuracy regression.

## Out of scope

- Selecting a specific commercial provider or negotiating quotas without enterprise contract data.
- Autonomous execution of destructive IT remediation.
- Replacing the ITSM system, frontend framework, primary database, or all existing AI prompts.
- Building a GPU inference platform solely to satisfy this user-count statement.
- Claiming final production capacity without observed arrival rates, prompt/token distributions, provider telemetry, and load tests.

## Required voter checklist

Each voter must return a complete proposal covering acceptance requirements, all options and relevant hybrids, implementation detail, compatibility, failure paths, rollback, stop conditions, retained unknowns, scope exclusions, risks, and adversarial checks. The proposal verdict must be `PROPOSE` and bind to this exact brief as version `v0`.
