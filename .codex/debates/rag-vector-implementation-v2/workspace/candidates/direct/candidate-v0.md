debate-protocol: 2
debate-scope: direct
debate-version: v0

# Tickety RAG/vector implementation decision

## Decision

Implement a parallel, chunked PostgreSQL/pgvector v2 store with deterministic hybrid full-text/vector retrieval, shared query-embedding cache, and one immutable authorized context snapshot reused by both same-model agents.

The selected target is **B + C + F1 + G2 + G4**:

- implement lexical/vector hybrid retrieval with Reciprocal Rank Fusion;
- add a parallel chunked v2 pgvector table and retain v1 for fallback/rollback;
- use deterministic ranking, authority and diversity—no LLM or separate-model reranker;
- cache only query embeddings in PostgreSQL, never complete retrieval results;
- persist one short-lived authorized context snapshot per AI job/request for the triage agent and conditional resolution/review agent.

Use Option A tuning as an early phase. Reject in-place v1 alteration. Defer an external vector database until measured pgvector failure at production-shaped scale. This plan uses one production LLM model; the retrieval subsystem adds no model.

## Schema and dimension contract

Add Alembic migration `0008_rag_hybrid_chunks_v2.py`. Before DDL, PostgreSQL preflight reads the dimension of the existing `ticket_search_documents.embedding` column and compares it with the validated deployment-owned `TICKET_EMBEDDING_DIMENSIONS`. Abort on absence or mismatch. Record the fixed dimension and chunker identity in `rag_v2_schema_meta`. A future model dimension change creates v3; never alter an indexed vector dimension in place.

Create `ticket_search_chunks_v2`:

- `chunk_id CHAR(64)` primary key;
- `scope_key VARCHAR NOT NULL`, derived from deployment/workspace/binding context, never caller-supplied;
- `source_type`, `source_id`, nullable `ticket_id`, `chunk_index`, `section_path`;
- bounded `content`, `content_hash`, `parent_hash`, `source_revision`, `chunker_identity`;
- safe `metadata_json` for display only—never trusted for authority;
- nullable `embedding vector(D)`, `embedding_identity`, `embedded_at`;
- `embedding_state` (`queued|running|ready|dead_letter`), attempts, `not_before`, lease ID/owner/expiry, and bounded error code;
- created/updated timestamps;
- unique `(scope_key, source_type, source_id, parent_hash, chunk_index)` and `CHECK(chunk_index >= 0)`.

Indexes:

- HNSW `(embedding vector_cosine_ops)`;
- GIN on `to_tsvector('simple', COALESCE(section_path,'') || ' ' || COALESCE(content,''))`, preserving v1's `simple` configuration;
- btree `(scope_key, source_type, source_id)`, `ticket_id`, and `(scope_key, embedding_identity)`;
- partial embedding-queue index `(not_before, updated_at)` where state is `queued`;
- partial expired-lease index on `lease_expires_at` where state is `running`.

Create `rag_query_embedding_cache_v2` keyed by `(scope_key, query_hash, embedding_identity, dimensions)`, containing only the vector, creation/access/expiry, and hit count. Store no raw query. Default TTL is 45 minutes with a bounded row limit and periodic deletion. It stays within the existing PostgreSQL trust boundary and inherits query data classification. Every cache hit still performs live retrieval authorization.

Create `rag_context_snapshots_v2`: ID, optional AI job/request ID, scope key, actor/auth fingerprint, corpus generation, embedding identity, query hash, bounded packed evidence JSON, exact chunk IDs/content hashes/citations, digest, created/expiry. Default expiry is the smaller of job retention and 24 hours. The snapshot contains already-redacted bounded excerpts, not a raw prompt or raw provider response.

Create `rag_corpus_generations_v2(scope_key, generation)`. Increment it in the same transaction as any source chunk replacement/removal or authorization-relevant source change.

## Deterministic chunking and source lifecycle

Add an explicit `tiktoken` dependency and use a fixed `cl100k_base` chunker identity such as `rag-v2-cl100k-450-50`. Split in this order: headings, paragraphs, sentences, then token windows. Bootstrap target 450 tokens, maximum 600, overlap at most 50 tokens at natural boundaries. Short ticket descriptions and comments remain single chunks.

Limits are explicit and non-silent: maximum 16 chunks for a ticket description, 8 for one comment, and 128 for one KB article. Oversized sources are marked with a safe indexing error and operator metric; they are not silently truncated.

For each eligible source, compute canonical parent hash and chunks. `chunk_id = SHA256(scope_key|source_type|source_id|parent_hash|chunk_index|chunker_identity)`. In one short transaction, re-read authoritative eligibility and revision, delete prior chunks for that source, insert the exact new chunks with `embedding_state=queued`, and increment corpus generation. No provider call occurs in this transaction.

Delete all chunks immediately when a source is deleted, archived, unpublished, becomes portal evidence, loses independent KB approval, or becomes private under current policy. Model-generated summaries/reasoning/plans never enter the chunker.

During the short embedding lag, FTS sees current text and vector search ignores null embeddings. This is safer than retaining stale old vectors. Citations reference chunk ID, parent source, section, and content hash, while live authority always resolves from current ticket/comment/KB tables.

## Batched embedding worker

Do not block this RAG upgrade on the broader proposed `ai_jobs` system. Use the narrow durable lease fields on v2 chunk rows. Integrate a long-lived embedding loop in a new `app/backend/rag/embedding_worker.py`, started from the dedicated worker process.

Workers claim up to 32 eligible chunks with `FOR UPDATE SKIP LOCKED`, fresh leases and bounded attempts, then commit before the provider call. A periodic scan recovers expired leases, so missed wake-ups and worker death do not lose work.

Add `_embed_texts(inputs)` that sends one provider batch, bounded by provider contract, total characters/tokens, RPM/TPM/daily budget, and shared concurrency. Keep current redaction, endpoint validation, timeout and embedding identity rules. Require exactly one finite vector of exact dimension D for every returned item.

Maximum two attempts per chunk with exponential jitter. A malformed/partial batch is split to isolate a toxic item; valid items may commit independently. Immediately before each update, require matching chunk ID, content hash, parent hash, source eligibility/revision, embedding identity, and active lease. A delayed result that fails this predicate is discarded or requeued; it never resurrects stale evidence. Dead-letter chunks remain searchable lexically but not semantically and are visible to operators.

## Hybrid retrieval algorithm

Implement v2 behind a facade in `ticket_vectors.py`; put new code in `app/backend/rag/chunking.py`, `store_v2.py`, `retrieval_v2.py`, `snapshots.py`, and `embedding_worker.py`.

For a query:

1. Compute canonical embedding input with NFKC normalization, trim and whitespace collapse. Hash `scope_key|canonical_query|embedding_identity|D`.
2. Start authorized FTS candidate retrieval in `asyncio.to_thread`; its function opens and closes its own `SessionLocal`.
3. In parallel, read the shared query-vector cache or call the embedding provider without an open request transaction.
4. If a vector is available, run vector retrieval in another independently owned short-lived session. Never share a SQLAlchemy session across threads/tasks.
5. Both lexical and vector SQL apply current portal/private/assignee/KB/source predicates before each candidate limit. Metadata JSON cannot upgrade authority.
6. Keep separate bootstrap pools: 40 lexical and 40 vector ticket/comment chunks; 16 lexical and 16 vector published-KB chunks.
7. Rank each pool from 1. For chunk `d`, compute `RRF(d)=Σ 1/(60+rank_signal(d))`. Never compare raw FTS and cosine scores.
8. Tie-break by presence in both signals, authoritative priority, best individual rank, then stable `(source_type, source_id, chunk_index, chunk_id)`.
9. Deduplicate normalized passages; cap at two chunks per parent and two non-KB chunks per ticket. Reserve up to two eligible published-KB passages when available. Return 6–10 passages within the existing prompt budget.

Vector/cache/provider failure degrades to authorized lexical results. Database or authoritative-check failure fails closed. Full retrieval-result caching is deferred because authorization and corpus invalidation are not yet worth its risk.

## Two agents, one model, one snapshot

After retrieval, pack the bounded evidence exactly once and persist the snapshot with current auth fingerprint, corpus generation, embedding identity, source/chunk hashes, citation allowlist and digest.

The triage/retrieval agent binds to `snapshot_id` and digest. The conditional resolution/review agent receives the exact same packed evidence and citation allowlist on the same production model. It does not run retrieval again.

Before reuse, verify actor/scope/auth fingerprint, expiry, embedding identity, corpus generation, and live authorization/content hash for every source. Any mismatch discards the snapshot and performs fresh retrieval. Generated agent output is never appended to the snapshot as evidence and never indexed.

## File-level implementation map

- `migrations/versions/0008_rag_hybrid_chunks_v2.py`: additive tables/indexes/meta/dimension preflight.
- `requirements.txt` and lockfile: explicit tokenizer dependency.
- `app/backend/rag/*`: chunking, store, retrieval, cache/snapshot, embedding worker.
- `app/backend/ticket_vectors.py`: v1/v2 facade, shared security/provenance shaping, status/reconciliation.
- `app/backend/worker.py`: start/stop embedding loop; no scheduler duplication.
- `app/backend/main.py` and AI job/contract paths: feature-flagged retrieval, snapshot creation and same-snapshot agent binding.
- `app/backend/settings.py`, `.env.example`, Helm values/schema/config: validated flags, dimension/chunk/batch/cache limits, scope allowlist.
- `tests/test_rag_v2_*.py`: chunk/RRF/cache/snapshot/lease/security tests; retain all v1 poisoning tests.
- CI: PostgreSQL pgvector integration job for real HNSW/GIN/migration/query plans.
- `scripts/benchmark-rag-v2.py` and `docs/rag-v2.md`: labelled evaluation, load/failure procedure, operations and rollback.

## Rollout and rollback

1. **Baseline:** build the labelled set, capture v1 relevance/latency/provider/DB metrics, validate dimension and migration query plans.
2. **Additive write:** create v2, flags default off, enable bounded dual-write and embedding worker for a scope allowlist. V1 remains authoritative.
3. **Backfill/shadow:** backfill in small batches with CPU/IO/rate-limit throttles; reconcile expected parent hashes/chunk IDs; shadow v2 reads without user-visible results.
4. **Canary read:** enable v2 hybrid retrieval for internal/low-risk scopes; both agents use snapshots; compare relevance, security and performance.
5. **Cutover:** expand scope only after all gates pass. Keep v1 dual-write and one-click read rollback through a defined retention window.
6. **Retirement:** separately approve v1 deletion only after sustained zero unauthorized/stale evidence, bounded divergence resolved, rollback drill passed, and audit retention satisfied.

Rollback is a feature-flag flip to v1/keyword reads plus pause of v2 backfill/worker claims. The additive schema remains for diagnosis. Never require a destructive database downgrade.

## Gates, observability and failure tests

Bootstrap release gates, not promises:

- v2 Recall@5/10, MRR or NDCG@10, relevant published-KB presence, grounded citations/actions and no-answer precision are not below the accepted v1 baseline;
- warm retrieval p95 under 250 ms, cached-query retrieval p95 under 400 ms, cold embedding plus retrieval p95 under 2 seconds;
- ordinary indexing freshness p95 under 60 seconds;
- zero portal/private/cross-assignee/unapproved/generated/stale evidence;
- no material ticketing API latency/error-budget regression during search/backfill;
- production-shaped observed corpus plus 100,000 chunks passes; run a 1,000,000 safe synthetic-chunk test before considering external infrastructure.

Measure query-cache hit/miss/age, batch size/utilization/provider latency, queue depth/age/retry/dead letter, index lag/stale identity, v1-v2 divergence, retrieval p50/p95/p99, FTS/vector query time and rows, HNSW/GIN/index sizes, DB CPU/IO/locks, selected passages/prompt tokens, and LLM latency separately. Telemetry uses safe IDs/hashes/classes only.

Inject timeout, partial/malformed/wrong-dimension batch, toxic item, delayed result after edit/delete/unpublish, worker death, missed wake-up, DB restart, stale cache/snapshot, portal/private/cross-assignee/unapproved source, duplicate/chunk flood, and no-answer query. Reconciliation must map every eligible source to its exact current chunks and every ready vector to its current identity.

Stop promotion and revert reads to v1 on any unauthorized/stale evidence, citation allowlist bypass, unexplained reconciliation loss, dimension mismatch, relevance regression, latency/freshness gate miss, provider-budget overrun, ticketing DB/API regression, or failed rollback drill.

## Option ledger

| Option | Decision |
|---|---|
| A tune v1 | Phase only: baseline, cache/batch primitives and fallback |
| B hybrid FTS+vector | Implement now with pre-limit security and RRF |
| C parallel chunked v2 | Adopt target; additive and reversible |
| D alter v1 in place | Reject: unsafe uniqueness/read compatibility and rollback |
| E external vector DB | Defer; reconsider only after tuned pgvector misses measured gates/headroom, typically at validated high corpus/multi-region need |
| F1 deterministic RRF | Adopt |
| F2 same-LLM rerank | Defer; only if labelled relevance remains inadequate and latency/cost/injection tradeoff is explicitly approved |
| F3 separate reranker | Reject: violates one-model constraint |
| G1 local query cache | Optional small L1 later; not required |
| G2 PostgreSQL query-vector cache | Adopt with tenant scope, hash-only key, TTL and live authorization |
| G3 result cache | Defer/reject initially |
| G4 job context snapshot | Adopt; required for two-agent reuse |

## Retained unknowns and scope

Unknowns remain: actual corpus/QPS/repetition/source lengths, provider batch contract/latency, DB headroom, acceptable audit retention, and labelled relevance baseline. Replace bootstrap values through baseline, contract review and production-shaped tests before cutover.

Out of scope: code changes in this debate turn, a second production model/reranker, database replacement without evidence, autonomous remediation, indexing secrets/generated/unapproved/portal/private evidence, or capacity/relevance claims without measurement.
