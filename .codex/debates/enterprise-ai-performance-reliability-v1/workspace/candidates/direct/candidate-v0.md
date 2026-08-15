debate-protocol: 2
debate-scope: direct
debate-version: v0

# Enterprise AI/LLM performance and reliability decision

## Decision

Adopt a PostgreSQL-first durable AI job system with scalable asynchronous workers, combined with an application-owned, task-aware provider policy.

In the option vocabulary from the brief, this is **B + D**, delivered through **A then B**, with a measured **B now, C later** path:

- Immediately harden and instrument the current system, but do not treat the single APScheduler worker or request-bound LLM execution as the target.
- Make PostgreSQL the durable source of truth for per-artifact AI jobs. API processes only admit work and return a durable job identity; worker replicas perform model calls.
- Add task/model routing, shared circuit breakers, and bounded fallback only between independently approved provider-region routes.
- Use PostgreSQL `LISTEN/NOTIFY` only as a best-effort wake-up; polling and leases remain authoritative.
- Do not add Redis, RabbitMQ, Kafka, Celery, or a managed queue initially. Add a durable broker only after measured PostgreSQL queue limits are crossed, using a transactional outbox.
- Do not self-host general-purpose inference for this user count. Reconsider it only for a separately proven regulatory, residency, or sustained-utilization case.

This is proportionate for 300–400 named ITSM users because licensed users are not the capacity unit. The real capacity units are admitted jobs per minute, calls per job, token distribution, provider quotas, model latency, cache reuse, tenant skew, and backlog age.

## Why this wins

The existing code already contains most correctness primitives: database-backed provider admission, ticket claims and leases, retries, dead-letter status, source hashes, model/pipeline provenance, exact artifact reuse, structured-output validation, and safe provider boundaries. The missing layer is a normalized durable job and a worker runtime that can scale without holding API requests or serializing the entire queue.

This design therefore removes the largest reliability and latency coupling with an additive change, not a rewrite. It also avoids introducing a second distributed system before the workload proves PostgreSQL insufficient.

## Target topology

Start with:

- 2 API replicas across failure domains. They perform authorization, validation, exact-reuse checks, durable admission, and job/status/event APIs. They do not wait for long LLM pipelines.
- 2 AI worker replicas across failure domains, each with 6 long-lived asynchronous execution slots. A replica-local slot is only a ceiling; every provider call must also acquire shared provider/model/task/tenant admission.
- A bootstrap shared provider cap no greater than 12 in-flight calls and always lower if the contracted quota formula requires it. The release is blocked if this safe cap cannot meet the load gate.
- 1 scheduler/sync owner for periodic ITSM synchronization and housekeeping only. It no longer executes the AI backlog serially.
- PostgreSQL/pgvector as the job, artifact, lease, budget, metric, and retrieval system of record.

Helm changes are explicit and additive:

- make `worker.replicaCount` configurable and start at 2;
- keep API `replicaCount` at 2 for the enterprise profile;
- add PodDisruptionBudgets with `minAvailable: 1` for API and workers;
- use `maxUnavailable: 0, maxSurge: 1` for API and `maxUnavailable: 1, maxSurge: 1` for workers;
- add topology spread or required pod anti-affinity across hostname and, when labelled, zone;
- give workers readiness based on database/schema access plus successful job-loop initialization, and liveness based only on process/event-loop health;
- use a bounded termination grace period: stop claims, mark the pod unready, drain active jobs, renew their leases while draining, then abandon uncompleted leases for expiry/reclaim rather than writing after ownership is lost;
- do not enable queue-driven autoscaling until queue metrics and scale safety tests exist. Retain `minReplicas: 2`; initially cap manual scale at 4 workers.

Core ticketing readiness must never depend on external LLM health. AI provider failure changes AI job state and circuit metrics, not the health of ticket CRUD.

## Durable data model

Add an Alembic migration with two tables. Use the repository's portable identifier convention (`String(36)` UUID text) unless a native UUID migration is separately approved.

`ai_jobs`:

- `id` primary key;
- `tenant_scope` non-null, derived from the authenticated deployment/workspace/integration binding, never directly trusted from the request; a single-tenant deployment uses one fixed scope;
- `ticket_id` nullable foreign key and indexed;
- `artifact` non-null enum-constrained string such as `triage`, `summary`, or `resolution`;
- `priority_class` non-null enum-constrained string: `interactive`, `background`, or `backfill`;
- `state` non-null enum-constrained string: `queued`, `running`, `retry_wait`, `succeeded`, `failed`, `dead_letter`, `cancelled`, or `blocked`;
- `idempotency_key` non-null SHA-256 hex generated from the business identity; unique with `tenant_scope`;
- `input_hash`, `pipeline_version`, and `route_policy_version` non-null;
- `route_snapshot` JSON/JSONB containing only non-secret route identifiers, region, model, task limits, and allowed secondary identifiers;
- `payload_ref` pointing to the authorized ticket/version rather than duplicating prompt or ticket text;
- `result_artifact_id` nullable foreign key to the existing artifact record; no large provider body is stored on the job;
- `attempt_count`, `max_attempts`, `not_before`, `lease_id`, `lease_owner`, `lease_expires_at`, and `heartbeat_at`;
- `last_error_class` and `last_error_code` from a bounded safe vocabulary, never raw exceptions or provider bodies;
- `created_at`, `updated_at`, `started_at`, and `completed_at`.

Use these indexes:

- a partial eligible-work index ordered by `(priority_class, not_before, created_at)` for states `queued` and `retry_wait`;
- a partial expired-lease index on `lease_expires_at` for state `running`;
- `(tenant_scope, state, updated_at)` for operations and per-tenant fairness;
- `(ticket_id, artifact, created_at)` for reconciliation and user status;
- `(state, updated_at)` for failed/dead-letter retention;
- unique `(tenant_scope, idempotency_key)`.

The idempotency key includes tenant scope, ticket ID/version, artifact, normalized input hash, pipeline version, route-policy version, and request generation. An explicit force-regeneration creates a new authorized generation rather than bypassing uniqueness. Concurrent duplicates return the current matching job or valid exact artifact.

`ai_job_events`:

- `(job_id, sequence)` composite primary key;
- bounded event type, safe stage, safe reason code, and creation time;
- optional small JSON metadata with an 8 KiB application limit and no ticket content, prompt, secret, provider body, or stack trace.

Events are monotonic and append-only for: accepted, queued, claimed, stage started/completed, retry scheduled, blocked, and terminal state. Retain terminal jobs/events for 30 days by default, then archive aggregate metrics and delete in bounded batches subject to enterprise audit requirements. Artifact retention remains governed separately.

## Admission and client lifecycle

For an interactive request:

1. Authenticate and authorize the caller against the ticket and requested artifact.
2. Apply existing user/tenant request quotas before creating expensive work.
3. Compute the current input hash, pipeline identity, and route-policy version.
4. In one database transaction, return a valid exact artifact or active matching job when present; otherwise insert the job and its accepted event.
5. Commit, then send PostgreSQL `NOTIFY` as a hint. Notification failure is harmless because workers poll.
6. Return `202 Accepted` with `job_id`, state, status URL, event URL, safe estimated class rather than a false precise ETA, and `Retry-After` for polling. Cached exact artifacts may still return immediately.

Expose:

- `POST /tickets/{id}/ai-jobs` with an artifact set and optional caller idempotency key;
- `GET /ai/jobs/{job_id}` for authorized durable state and result references;
- `GET /ai/jobs/{job_id}/events?after=<sequence>` for polling or SSE replay;
- an optional WebSocket mirror for low-latency progress, never the sole source of truth.

Refresh, reconnect, API rollout, API crash, worker rollout, and worker crash all recover from the database job and event sequence. If admission itself cannot commit, return a failure and do not claim the work was accepted.

## Worker lifecycle and correctness

Replace repeated `asyncio.run` calls with one long-lived event loop per worker process.

Each worker:

1. alternates weighted queries across interactive and non-interactive pools, borrowing idle capacity but guaranteeing at least 25% of call permits to background/backfill when both classes have eligible work; background age increases effective priority;
2. selects a small eligible batch with `SELECT ... FOR UPDATE SKIP LOCKED`, ordered within a class by `not_before, created_at`;
3. atomically sets `running`, a random lease ID/owner, an expiry, heartbeat, and started time, then commits before external work;
4. acquires replica-shared admission for the resolved provider/region/model, task, tenant, and user/system actor, followed by the local semaphore;
5. loads the authoritative ticket and recomputes input/pipeline/route identity before dispatch;
6. renews the job lease between pipeline stages and during long calls, without extending a lease after drain deadline;
7. conditionally commits a result only where job state is `running`, lease ID matches, lease is unexpired, and input/pipeline/route identity is still current;
8. writes through the existing provenance-aware artifact path, links `result_artifact_id`, appends a terminal event, and releases admission.

A zero-row conditional update means ownership or input was lost. Discard that output, record a safe stale-result metric, and never overwrite newer ticket state.

Delivery is at least once. External timeout after submission is ambiguous and may be billed even without a response. Use a stable provider correlation/idempotency key where supported. Whether or not the provider supports it, idempotent conditional database commitment prevents duplicate product effects; cost telemetry exposes uncertain duplicates.

Expired running leases are reclaimed to `retry_wait` if the total job attempt policy permits, otherwise `dead_letter`. Cancellation only prevents unstarted/retry-wait work or suppresses a later result commit; it cannot promise that an already submitted provider call was cancelled.

## Retry, circuit breaker, and fallback policy

Refactor retry ownership so nested loops cannot multiply attempts. The route policy owns one total external-call budget per artifact. `LLMManager` must accept an explicit single-attempt or remaining-attempt limit instead of always performing three attempts inside every job attempt.

Bootstrap maximum: 3 external calls per artifact across all routes, normally 2 primary attempts and at most 1 approved-secondary attempt. Every dispatch reserves RPM, TPM, daily tokens, and cost before the call.

Failure classes:

- Retry with bounded exponential full jitter and `Retry-After`: connection interruption, timeout, HTTP 408/429/500/502/503/504, and provider-declared temporary overload.
- Permit at most one repair/retry for schema-invalid or semantically invalid structured output, still inside the same total three-call budget and total deadline.
- Do not retry or fallback: bad credentials, invalid configuration/model, unapproved host, malformed input, authorization failure, data classification/residency denial, or budget/policy rejection.
- Move exhausted temporary or repeated invalid-output work to `dead_letter`; place policy/config/auth failures in `blocked` or terminal `failed` with a safe operator reason.

Add a shared route circuit record keyed by provider, region, model, and task route. Bootstrap thresholds, to be tuned from evidence:

- open after at least 5 eligible observations in 60 seconds when retryable failure/timeout rate is at least 50%, or after 5 consecutive eligible failures;
- cool down for 30 seconds;
- half-open with no more than 2 probe calls;
- close after both probes succeed, otherwise reopen with a bounded increasing cooldown.

Circuit changes are atomic, audited, and observable. They do not count authorization, policy, residency, budget, or caller-input failures against provider health.

Fallback is route-specific and disabled by default. Enable it only where an approved registry proves equivalent data classification, region/residency, contractual processing, schema compatibility, task quality, budget, and incident ownership. Never fallback for policy, residency, authentication, or configuration failure. If no approved secondary exists, keep eligible work in bounded retry/deferred state and show a transparent provider-unavailable reason; do not cross a trust boundary to meet latency.

## Model routing and direct LLM performance

Create a versioned approved model registry with:

- provider, region, endpoint identity, model, task eligibility, and output schema;
- data classification and residency approval;
- prompt/output token ceilings, cost ceiling, RPM/TPM and concurrency policy;
- quality-evaluation version and minimum score;
- primary and optional approved secondary;
- circuit and timeout policy.

Snapshot non-secret route identifiers at admission so a job is reproducible and auditable. A policy update applies to newly admitted jobs; operators explicitly requeue old work under a new generation when appropriate.

Use a qualified fast/low-cost route for routine classification only after evaluation. Use the stronger qualified route for summaries and resolution recommendations where its measured quality benefit warrants cost/latency. Prepare local routing and retrieval context concurrently where dependencies allow. Preserve prompt character/token budgets, select only provenance-safe relevant context, and use provider prompt-prefix caching only if contractually approved and its cache key cannot leak tenant data.

Keep exact artifact reuse only when tenant/ticket input, pipeline, route/model identity, and authorization scope match. Do not semantic-cache final ticket decisions. Deterministic retrieval or preprocessing caches require tenant scope, input/version identity, TTL, invalidation, and proof that stale reuse cannot alter the decision.

An experiment may combine compatible triage and summary outputs into one strict structured call, but it is not part of the initial correctness migration. Promote it only if a representative labelled evaluation shows no quality or safety regression and load tests show material latency/token benefit. Route remains local; resolution may remain dependent on validated earlier output.

## Bootstrap capacity model

Treat the following as load-test inputs, not promises:

- 400 named users;
- 80 concurrent interactive sessions at peak;
- 30 interactive AI jobs/minute for 15 minutes and a one-minute burst of 60;
- measured artifact mix, with a worst test of up to 3 external calls per full analysis;
- a 1,000-job background backlog while interactive work continues;
- 2 API replicas and 2 workers with 6 local slots each;
- shared provider in-flight cap at most 12 and lower when contract limits require it.

For a route with average observed call latency `L` seconds, average total tokens `T`, provider RPM, provider TPM, and a contractual concurrency cap, calculate a conservative steady-state ceiling:

`C_safe <= min(contract concurrency, RPM * L / 60, TPM * L / (60 * T), internal risk cap)`.

Use p75 rather than mean latency/tokens for the first release and reserve at least 20% quota headroom. Validate burst behavior separately because minute windows and output variance can dominate the average. If safe contracted capacity cannot meet the SLO workload, block broad rollout and obtain quota, reduce admitted workload, improve exact reuse/prompt cost, or approve another route; do not bypass admission.

Add worker replicas only when eligible queue age or interactive queue wait breaches SLO while PostgreSQL claim latency/CPU/IO/lock waits and provider quota headroom are healthy. Adding replicas must not multiply shared budgets.

## Broker and self-hosting triggers

Keep PostgreSQL until repeated representative tests or production traces show one of these after query/index/retention/batching tuning:

- eligible claim query p95 above 50 ms or queue polling consumes more than 10% of database CPU/IO budget;
- database CPU above 60% sustained, material lock waits, or queue-table growth threatens ticketing headroom;
- interactive queue-wait SLO fails while worker and provider headroom exist;
- active queue regularly exceeds 100,000 jobs or multi-region/sub-250 ms dispatch becomes a real requirement;
- another independently deployed consumer requires durable fan-out.

Then evaluate a durable managed queue or broker with a transactional outbox. PostgreSQL job identity, idempotency, and conditional artifact commit remain authoritative. Redis Pub/Sub or a plain list is not an acceptable durable queue.

Reconsider self-hosted inference only after a separate decision establishes a regulatory/residency need or sustained utilization that improves total cost while meeting quality, HA, patching, security, evaluation, and 24x7 operational ownership. It is not a fallback merely because a hosted provider is unavailable.

## SLOs and release gates

Until production traces ratify them, these are rollout gates:

- core ticketing API monthly availability at least 99.9%, measured independently of AI health;
- durable AI admission p95 under 1 second and p99 under 2 seconds;
- normal-load interactive queue wait p95 under 2 seconds;
- one-artifact completion p95 under 20 seconds;
- full-pipeline completion p95 under 60 seconds;
- at least 99.5% of eligible accepted jobs reach valid terminal success within 5 minutes, excluding explicit policy/budget rejection;
- zero silently lost accepted jobs;
- after a 15-minute provider outage at bootstrap load, interactive SLO recovers within 10 minutes and accumulated background work drains within 60 minutes without violating quota, cost, or trust policy;
- per-task quality and structured-output validity meet or exceed the accepted labelled baseline.

Report provider time, queue time, retrieval/preprocessing time, and commit time separately so model slowness is not confused with platform saturation.

## Telemetry and alerts

Dashboard safe aggregate dimensions only: tenant scope, task, priority class, route/provider/model/region identifiers, worker replica, and release/policy version.

Metrics:

- admission latency, admitted/reused/rejected/deferred count and safe reason;
- queue depth and oldest age by class/tenant, claim latency, worker utilization, heartbeat age, lease expiry/reclaim, attempts, retry delay, DLQ count/age;
- provider latency percentiles, timeout/error class/429, circuit state, fallback use/denial, RPM/TPM/daily token and cost reservations/settlement;
- prompt/input/output token distributions, exact reuse, end-to-end completion, structured-output validity, labelled quality sample results;
- stale/lost-lease commit rejection, reconciliation mismatch, and uncertain timeout-after-submit count;
- core API saturation/availability separately from AI SLOs.

Never place raw ticket content, prompts, secrets, credentials, provider response bodies, or stack traces in metrics, events, or routine logs.

Page on core API/error-budget burn, any accepted-job-loss invariant, stale overwrite or reconciliation mismatch, sustained interactive queue-age burn, prolonged open circuit, quota/budget exhaustion, DLQ growth/age, lease-expiry spike, queue/database saturation, significant quality regression, or attempted unapproved fallback. Create non-page work items for isolated invalid outputs and transient retry noise.

## Verification matrix

Before broad rollout, require:

- migration lock-time and query-plan tests on a production-shaped database;
- unit/property/concurrency tests for duplicate enqueue, unique idempotency, `SKIP LOCKED` claims, lease heartbeat/expiry race, worker death, duplicate completion, changed ticket input, lost lease, stale route/pipeline, cancellation, and conditional commit;
- client refresh/reconnect, API restart/rolling update, worker kill/rolling update, database connection interruption/failover, missed `NOTIFY`, and event replay tests;
- provider timeout before and after likely submission, 408/429 with `Retry-After`, 5xx, malformed/invalid structured output, bad auth/config, policy/residency denial, circuit open/half-open, approved fallback, and denied fallback tests;
- a noisy-tenant and priority-abuse test proving tenant/user caps and at least 25% background service when both classes are backlogged;
- 30 jobs/minute sustained, 60/minute burst, 1,000-job backlog plus new interactive work, one-worker loss, and 15-minute provider outage/recovery;
- a capacity ramp to at least 2 times the measured production peak or the bootstrap peak, whichever is higher, without exceeding approved provider/database headroom;
- task-specific labelled quality and cost comparison for every model route and any prompt-consolidation experiment;
- reconciliation showing every accepted job is terminal, active with a live lease, or deliberately queued/retry-wait—never missing.

Pass only if all stated SLO, no-loss, quota, quality, stale-write, and data-boundary assertions pass. A failed gate blocks cohort expansion.

## Migration and rollout

### Phase 0 — Baseline and immediate hardening

Instrument current queue wait, provider time, token use, artifact mix, exact reuse, job outcome, and database headroom over representative peaks. Define data classifications, approved routes, labelled quality baselines, budget owner, feature flags, and kill switches. Correct retry classification and ensure existing same-provider retries cannot multiply with later job attempts.

Stop if telemetry privacy, provider/residency approval, quality threshold, or budget ownership is unresolved.

### Phase 1 — Additive schema, no behavior change

Ship `ai_jobs`, events, indexes, route/circuit records, reconciliation tooling, metrics, and configurable worker replica/chart primitives with the new engine disabled. Do not auto-backfill active work. Validate migration lock time and query plans.

Stop or roll application behavior back if ticketing database latency/error budget regresses or ownership reconciliation is ambiguous. Keep the additive schema.

### Phase 2 — Low-risk canary

Enable the new engine for internal users or one low-risk artifact, with 2 workers, a low shared provider cap, and no cross-provider fallback. Use an explicit engine discriminator so legacy and new workers can never process the same logical request.

Stop admissions for the cohort on accepted-job loss, stale overwrite, core API regression, sustained SLO failure, budget/quota breach, or privacy/security incident. Drain or expire leases, reconcile, and use the prior path only after verifying idempotency/provenance.

### Phase 3 — Enterprise interactive rollout

Enable durable interactive jobs, 2 API replicas, 2 workers, fair scheduling, route policy, and circuits. Enable a secondary only after its task quality, residency, quota, schema, and incident tests pass. Expand cohorts only after at least 7 days or a statistically adequate job volume meets SLO, quality, cost, and no-loss gates.

### Phase 4 — Full pipeline and background work

Move full pipelines and controlled backfill, tune provider/worker caps from telemetry, drill provider outage and backlog recovery, and run the rollback procedure. Broad rollout requires no unresolved critical DLQ/reconciliation finding and a successful rollback/drain drill.

## Rollback and operator runbooks

The migration is additive. Preserve existing ticket queue fields during the rollback window.

Rollback behavior:

1. disable new-engine admissions by tenant/task;
2. mark workers unready and stop new claims;
3. drain active jobs for a bounded window while heartbeating;
4. let unfinished leases expire; do not force a result commit;
5. reconcile jobs against current ticket input and artifact provenance;
6. requeue eligible work under exactly one engine after operator approval;
7. retain jobs/events for audit and diagnosis rather than rolling back the schema.

Runbooks must cover pause/resume by tenant/task/route, safe job inspection, blocked versus retry/DLQ diagnosis, circuit state and audited override, configuration correction and controlled replay, stranded-lease reclaim, job/artifact reconciliation, worker drain, fallback disable, provider quota exhaustion, data-boundary incident, and core-ticketing escalation.

Automatic replay is forbidden for policy/residency denial, bad credentials/configuration, invalid host/model, poison input/output, or a job whose authoritative input changed. Operator replay creates a new audited generation when identity changes.

## Stop conditions

Freeze cohort expansion and disable affected admissions when any of these occurs:

- an accepted job is silently lost or a stale/lost-lease result overwrites current state;
- core ticketing availability or database error budget regresses because of AI workload;
- sustained queue/latency SLO breach without an understood safe capacity action;
- retry multiplication, quota overrun, unexpected cost burn, or DLQ flood;
- task quality or structured-output validity falls below baseline;
- raw sensitive content appears in telemetry;
- an unapproved provider, region, model, or fallback is attempted;
- rollback/drain/reconciliation cannot be demonstrated safely.

## Option ledger

| Option | Decision | Rationale, dependencies, risk, and trigger |
|---|---|---|
| A: tune current single scheduler and request-bound paths | Retain only for Phase 0 | Low-cost hardening and baseline evidence, but serial polling and provider latency inside API lifecycles cannot satisfy the target durability/throughput model. |
| B: PostgreSQL durable `ai_jobs` and async workers | Adopt | Best reuse and proportionality. Requires additive schema, worker loop, status/events, idempotent conditional commit, indexes, and operational tooling. Main risk is queue load on the primary database, covered by headroom gates and broker triggers. |
| C: broker/managed queue | Defer | Efficient wake-up and mature redelivery, but adds an availability/security/operations dependency and dual-write risk. Introduce only with transactional outbox after measured PostgreSQL thresholds. |
| D: task-aware provider policy, circuits, approved fallback | Adopt in application | Improves latency/cost/resilience and avoids same-route retry storms. Requires an approved registry, shared circuit state, quality evaluations, and route-level budget. Never crosses an unapproved residency or data boundary. A purchased gateway is optional only if it preserves these semantics. |
| E: self-hosted inference | Reject now; retain contingency | No current GPU/model operations evidence and likely poor economics at this scale. Reopen only for proven regulation/residency or sustained utilization with full HA/security/on-call case. |
| A then B | Adopt rollout path | Immediate evidence and hardening reduce migration risk; A must not become the permanent architecture. |
| B now, C later | Adopt evolution path | Keeps correctness in PostgreSQL and allows a broker without redesigning job identity or result commitment. |
| B + selective C (`LISTEN/NOTIFY`) | Adopt only as advisory wake-up | Reduces average polling delay with no delivery dependency. Missed notifications are recovered by polling. |
| D + E | Defer/reject | Hosted-primary/self-hosted fallback is unsafe until equivalent quality, approval, capacity, and operations are independently proven. |

## Retained unknowns

The following remain deliberately unresolved because the user count does not answer them:

- peak arrival distribution, artifact mix, calls per job, prompt/input/output token percentiles, model latency/error distribution, and exact reuse rate;
- provider RPM/TPM/concurrency contracts, approved provider/region set, data classifications, monthly budget, and recovery objectives;
- tenant/user demand skew, labelled task quality thresholds, PostgreSQL queue/result-storage headroom, and enterprise audit retention;
- whether the bootstrap SLOs are the enterprise's contractual SLOs or only internal release gates.

Resolve them with Phase 0 traces, the verification matrix, provider contracts, security/residency review, labelled evaluations, and production-shaped database tests. Do not convert bootstrap numbers into capacity promises before that evidence exists.

## Out of scope

- naming or negotiating a specific commercial provider;
- autonomous destructive remediation;
- replacing the ITSM system, frontend framework, or primary database;
- wholesale prompt replacement;
- building a GPU platform solely for 300–400 named users;
- claiming final production capacity without workload, token, quota, latency, quality, and database measurements.

Human approval remains required for high-impact actions. This decision governs analysis, summaries, routing suggestions, resolution recommendations, and retrieval only.
