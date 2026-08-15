# Canonical debate brief: implement faster and more reliable RAG in Tickety

## Destination

Produce one implementation-ready plan for upgrading Tickety's existing RAG/vector retrieval to improve latency, throughput, grounding quality, and operational reliability for an enterprise deployment with approximately 300–400 ITSM users.

The deployed runtime must use one approved production LLM model. It may use two logical agents on that same model: a triage/retrieval agent and a conditional resolution/review agent. The retrieval subsystem should be deterministic where possible, and both agents should reuse one authorized retrieval snapshot rather than independently retrieving the same context.

This debate decides the implementation plan; it does not authorize code changes in this turn.

## Requested output

Return a single decision artifact containing:

1. target retrieval and indexing architecture;
2. exact schema/migration approach and compatibility behavior;
3. deterministic chunking and source-provenance rules;
4. embedding refresh, batching, retries, and stale-write protection;
5. hybrid keyword/vector retrieval and ranking algorithm;
6. cache keys, TTLs, invalidation, and authorization boundaries;
7. integration with two agents using the same model;
8. implementation phases with file-level change map;
9. tests, benchmarks, SLO gates, observability, rollback, and stop conditions;
10. option ledger and retained unknowns.

Make a clear implement/defer/reject decision. Do not merely list best practices.

## Observed facts and source quality

The following were read directly from the current repository and are high-quality implementation evidence:

- `app/backend/database.py::_ensure_ticket_search_documents` creates a PostgreSQL `ticket_search_documents` table with one row per `(source_type, source_id)`, `vector(dimensions)`, a cosine HNSW index, a GIN functional full-text index, and keyword fallback when pgvector is unavailable.
- The default embedding model is `openai/text-embedding-3-small` with 1,536 dimensions. Model, dimensions, endpoint, timeout, and minimum score are deployment-configurable.
- `app/backend/ticket_vectors.py::_embed_text` sends one input per provider call. It uses secret redaction, endpoint validation, provider concurrency leases, RPM/TPM/daily-token reservation, timeout bounds, dimension validation, and safe failure logging.
- Source refresh currently processes tickets, comments, and KB articles sequentially. Backfill may visit up to 500 records per source family and awaits one embedding call per changed document.
- A document hash and embedding identity prevent unchanged rebuilds. Source revalidation after an embedding call prevents a delayed writer from resurrecting archived or superseded evidence.
- Tickets index subject plus original description, not model-generated summaries/reasoning/plans. Comments are separate evidence documents. Private comments are excluded unless explicitly enabled. Portal tickets are excluded.
- Only published KB articles with a reviewer, and with reviewer distinct from author when an author exists, are eligible. Unapproved KB documents are purged.
- Retrieval applies authoritative source, assignment, portal, private-note, and KB-approval checks before candidate limits. Tests explicitly require this fail-closed ordering.
- Vector retrieval and keyword retrieval are alternatives: if query embedding and vector search succeed, the function returns vector results; keyword retrieval is primarily a fallback rather than a concurrently fused signal.
- Non-KB and published-KB candidate pools are separate. Per-ticket candidate caps, normalized deduplication, authority tie-breaking, and a published-KB reservation reduce domination by comments or one ticket.
- Context packing includes bounded source fields, citations, safe metadata, authority, redaction, and a global character limit. Model citations outside the retrieved set are rejected. Actions are derived only from approved KB citations.
- Search and analysis are currently executed inside API request lifecycles. A cold vector query includes an external embedding request before database vector search.
- PostgreSQL/pgvector is already an application dependency and the Helm chart uses `pgvector/pgvector:pg16`. There is no external vector database, Redis, broker, separate reranker model, or dedicated embedding worker.
- Existing tests cover portal/private/assignment scope, authoritative-source checks before limits, prompt poisoning, delayed embedding races, stale embedding identity, per-ticket diversification, published-KB survival, backfill progression, and citation grounding.

The only workload input is approximately 300–400 users. Corpus size, queries per second, repetition rate, source length distribution, embedding-provider batch limits, provider latency, database headroom, and labelled retrieval relevance are unknown. Numerical settings must be labelled bootstrap values and gated by measurement.

## Constraints

- Use one production LLM model. Do not require a second generation model, a separate reranker model, or cross-model fallback.
- Two logical agents may use different prompts/contracts but the same model configuration. The second agent is conditional, not mandatory for every request.
- Keep PostgreSQL/pgvector unless measured evidence proves it cannot meet the workload after tuning.
- Preserve all current authorization, provenance, portal/private-note, assignment, KB approval, prompt-containment, citation, and fail-closed rules.
- Authoritative security predicates must be applied before candidate limits. Cached results may never bypass current authorization or source validation.
- Model-generated output must never become authoritative retrieval evidence.
- Do not hold database transactions or request sessions open across embedding-provider calls.
- Treat embedding calls as at least once. A late result may commit only if content hash, source state, and embedding identity are still current.
- Avoid raw queries, tickets, prompts, secrets, or provider bodies in routine telemetry. Persistent caches inherit the data classification of their source/query.
- Prefer additive migrations, feature flags, dual-read/dual-write compatibility, bounded backfill, and reversible cutover.
- Retrieval improvements may reduce tokens and retries but cannot accelerate the generation model itself; report retrieval and LLM latency separately.

## Acceptance requirements

1. **Implementation specificity:** name the schema, indexes, functions/modules, APIs/config, phased writes/reads, and cleanup path. Resolve whether to alter the current table or introduce a versioned parallel store.
2. **Hybrid retrieval:** combine lexical and semantic evidence when vector search is available, with deterministic score fusion that does not compare incompatible raw scores. Preserve separate KB capacity and per-ticket/source diversification.
3. **Chunking:** define deterministic chunk boundaries, size/overlap, identifiers, parent provenance, update/delete behavior, and citation behavior. Avoid indexing a huge article as one vector while preventing chunk flooding.
4. **Embedding throughput:** replace one-provider-call-per-document backfill with bounded batches and a durable or safely recoverable refresh mechanism. Preserve shared provider admission, stale-source checks, retry bounds, and dimension/identity validation.
5. **Cold-query latency:** define query-embedding caching and/or concurrency with lexical search. Cache keys and invalidation must include tenant/scope and embedding identity and must not store raw queries unnecessarily.
6. **Two-agent reuse:** create one immutable authorized context snapshot per AI job/request, reusable by both same-model agents. The second agent must not repeat retrieval unless source/corpus/auth identity changed.
7. **Security:** demonstrate that portal tickets, private comments, cross-assignee evidence, unapproved KB, stale documents, and model-generated artifacts cannot enter results through chunks, caches, fusion, or snapshot reuse.
8. **Performance/quality gates:** define bootstrap p95 latency targets, cache/batch/index-lag metrics, labelled Recall@K or NDCG/MRR evaluation, grounded citation/action checks, corpus-scale benchmark, and failure injection.
9. **Operational safety:** include additive migration, backfill throttling, feature flags, rollback, stop conditions, retention, index maintenance, and a no-loss/no-stale-write reconciliation.
10. **Proportionate infrastructure:** explicitly assess pgvector in-place changes, a parallel pgvector v2 store, an external vector database, deterministic reranking, LLM reranking, and caching levels.

## Material option families

### Option A — Tune the current whole-document vector-or-keyword implementation

- **Feasibility:** smallest change. Tune HNSW search parameters/candidate limits, cache query embeddings, and batch backfill while retaining one row per source.
- **Benefits:** low migration risk and fast delivery.
- **Costs/risks:** long KB articles remain poorly represented by one vector; vector and lexical signals are not fused; whole-document snippets may waste context; current table uniqueness prevents chunks.
- **Dependencies:** benchmarks, query cache, embedding batch helper.
- **Unknown:** may be sufficient if documents are short and relevance baseline is already strong.
- **Decision question:** target architecture or only an initial phase?

### Option B — Add true hybrid retrieval over the current store

- **Feasibility:** run FTS and vector candidate queries, preserve authoritative predicates, then fuse ranks using Reciprocal Rank Fusion or another deterministic rank-only method.
- **Benefits:** exact incident/error/product terms and semantic matches both survive; no extra generation model; easy A/B evaluation.
- **Costs/risks:** two searches consume more database work; a cold query still needs an embedding call; incorrect concurrency can share a non-thread-safe SQLAlchemy session; result fusion can reintroduce disallowed evidence if security filters are applied after limits.
- **Dependencies:** separate read sessions or one combined SQL plan, bounded candidate pools, deterministic fusion tests.
- **Decision question:** implement now, and with which execution pattern?

### Option C — Parallel chunked pgvector store (v2)

- **Feasibility:** introduce a new chunk table, seed/dual-write it, backfill in batches, shadow-read, then cut over. Keep the existing table for rollback.
- **Benefits:** safe additive migration, heading/paragraph-level KB retrieval, bounded passages, independent v1 rollback, better token efficiency and relevance.
- **Costs/risks:** temporary duplicate storage, more rows/index maintenance, chunk-flooding risk, configured vector dimension must be schema-compatible, and dual-write divergence needs reconciliation.
- **Dependencies:** deterministic chunker, new migration, embedding refresh state, v2 retrieval, backfill/reconciliation.
- **Decision question:** preferred implementation or unnecessary complexity at this scale?

### Option D — Alter the existing table in place for chunks

- **Feasibility:** add `chunk_index`/section fields, replace uniqueness, and rebuild documents/indexes.
- **Benefits:** one long-term store and less duplicate storage.
- **Costs/risks:** harder rollback; existing raw-SQL-created constraint names and configurable vector dimension complicate migration; current readers/writers/tests assume one row per source; partial deployment can corrupt compatibility.
- **Dependencies:** carefully ordered DDL, full reindex, coordinated deploy.
- **Decision question:** choose over parallel v2 only with compelling simplicity evidence.

### Option E — External vector database

- **Feasibility:** Pinecone, Qdrant, Weaviate, OpenSearch, or a managed equivalent could store chunks and metadata.
- **Benefits:** independent scaling, specialized filtering, managed replication, and possibly stronger very-large-corpus performance.
- **Costs/risks:** new data processor/trust boundary, network latency, dual-write/outbox and reconciliation, operations/cost, backup/DR, authorization-filter correctness, and no current workload evidence.
- **Dependencies:** product selection, security/residency approval, outbox, client, operational ownership.
- **Decision question:** reject/defer, with explicit triggers.

### Option F — Reranking choices

- **Deterministic RRF/authority/diversity:** no additional model, low latency, auditable; may be less semantically precise than a trained reranker.
- **Same-LLM reranking:** respects the one-model constraint but adds a generation call, cost, latency, nondeterminism, and prompt-injection surface.
- **Separate cross-encoder/reranker model:** often improves relevance, but violates the user's one-model constraint for the deployed solution.
- **Decision question:** choose deterministic fusion now; decide whether conditional same-model reranking belongs in scope.

### Option G — Cache levels

- **Process-local query embedding cache:** low implementation cost and no shared storage, but misses across replicas and disappears on restart.
- **PostgreSQL query embedding cache:** shared across replicas and avoids provider calls on repeated queries, but persists sensitive semantic vectors and needs tenant scope, TTL, dimension identity, retention, and authorization review.
- **Retrieval result cache:** can avoid vector/FTS work but has difficult source-version and authorization invalidation.
- **Packed-context snapshot:** necessary to share the exact authorized evidence between the two agents for one job; should use source IDs/chunk hashes and expire with the job/artifact policy.
- **Decision question:** implement the smallest safe cache set and defer unsafe complexity.

## Relevant hybrids to assess

- A + B: fast first release—batch embeddings, query cache, and hybrid fusion on whole documents.
- B + C: true hybrid search over a chunked v2 pgvector store.
- B + C + bounded cache: chunked hybrid retrieval with query-embedding cache and per-job context snapshot.
- C now, E later: preserve a provider-neutral retrieval interface and defer external vector infrastructure behind measured triggers.
- Deterministic RRF now, optional same-model conditional review later.

## Bootstrap implementation assumptions to challenge

- Corpus benchmark at 100,000 chunks plus a smaller observed-production corpus; scale test to 1,000,000 synthetic metadata-safe chunks before considering an external database.
- Chunk target around 350–500 tokens, maximum 600, overlap around 50 tokens, with heading/paragraph-aware boundaries. Ticket description and each comment remain distinct parents; only long parents split.
- Keyword and vector candidate pools around 40 each for ticket/comment and 12–20 each for published KB, fused with RRF constant near 60, then diversified to 6–10 prompt passages and no more than two chunks per parent/ticket.
- Batch embedding size 32, configurable down to provider contract; maximum two attempts per batch item with bounded jitter and split-on-invalid-item behavior.
- Query-embedding cache TTL 30–60 minutes, keying on tenant scope, normalized-query hash, embedding identity, and dimensions, storing no raw query.
- Retrieval result caching is deferred initially; one per-job context snapshot is persisted or referenced for reuse by both agents.
- Bootstrap targets: warm retrieval p95 under 250 ms; cached-query end-to-end retrieval p95 under 400 ms; cold query embedding plus retrieval p95 under 2 seconds; index freshness p95 under 60 seconds for ordinary changes; zero stale/unauthorized evidence.

The final candidate may change these values but must identify them as test inputs and provide tuning evidence.

## Required implementation details

The final candidate must decide and specify:

- exact v2 table and cache/snapshot schema or a justified in-place alternative;
- how vector dimension is locked and validated across deployment/migration;
- deterministic chunk IDs and replacement transaction;
- whether embedding work uses the previously proposed durable `ai_jobs` system, a narrow embedding lease state, or another explicit mechanism;
- the batch embedding response validation and per-item stale-write guard;
- exact RRF formula/tie-breaks and how duplicate chunks/parents are capped;
- how keyword search overlaps a cold query embedding without passing one SQLAlchemy session across threads;
- how authority and authorization predicates remain before every candidate limit and cache hit;
- how the two agents bind to one context snapshot and citations;
- file-level change map for database/migrations, retrieval module, API/job integration, settings/Helm/docs, and tests;
- rollout and rollback that do not require destructive database downgrade.

## Quantitative verification

Require a labelled evaluation set containing exact identifiers/error codes, paraphrases, long KB articles, competing comments, cross-assignee tickets, portal/private/unapproved poison cases, stale updates, and no-answer queries.

Measure:

- Recall@5/10, MRR or NDCG@10, published-KB presence where relevant, duplicate-parent rate, citation validity, grounded action rate, and no-answer precision;
- query-embedding cache hit/miss/age, provider latency and batch utilization, index lag/stale/failure/retry, v1-v2 divergence, retrieval p50/p95/p99, DB query time, rows examined, HNSW candidate behavior, prompt passage/token count, and end-to-end LLM latency separately;
- PostgreSQL CPU/IO/locks/index size and ticketing API latency under concurrent backfill and search.

Failure injection must include provider timeout/partial/malformed batch response, wrong dimension, one toxic item, delayed old embedding after source update/delete/unpublish, worker death mid-batch, missed wake-up, database restart, stale query-cache row, stale context snapshot, private/portal/cross-assignee/unapproved KB attempts, and duplicate chunk flooding.

## Out of scope

- Implementing the code in this debate turn.
- Adding a second production generation/reranker model.
- Replacing PostgreSQL without measured evidence.
- Autonomous destructive remediation.
- Indexing raw secrets, credentials, model-generated artifacts, unapproved KB, portal tickets, or private notes outside explicit policy.
- Claiming final capacity or relevance gains without labelled evaluation and production-shaped benchmarks.

## Required voter checklist

Each voter must cover every acceptance requirement, all options/hybrids, schema and algorithms, compatibility, failure paths, rollback, stop conditions, retained unknowns, scope exclusions, risks, and adversarial checks. Proposal verdict must be `PROPOSE`, version `v0`, bound to this exact brief digest.
