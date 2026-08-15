# Canonical brief: Tickety RAG/vector implementation

## Destination and format

Decide an implementation-ready RAG/vector upgrade for Tickety at roughly 300–400 ITSM users. The runtime uses one approved production LLM model with two logical agents on that same model: triage/retrieval and conditional resolution/review. Both agents reuse one authorized retrieval snapshot. This turn produces a plan, not code.

Return one concise decision artifact (target under 10,000 characters) with: target architecture; schema/indexes; chunking; embedding batches/recovery; hybrid algorithm; caches; two-agent snapshot integration; file-level changes; phased migration/rollback; tests/SLOs/metrics; option ledger; unknowns and stop conditions.

## Repository facts (direct code evidence)

- PostgreSQL/pgvector already stores one `ticket_search_documents` row per `(source_type, source_id)`, `vector(configured dimensions)`, cosine HNSW, and GIN FTS. Keyword fallback works without pgvector.
- Default embeddings are 1,536-dimensional `openai/text-embedding-3-small`; model/dimensions/endpoint/timeouts/score are configurable.
- `_embed_text` sends one input per call with redaction, validated endpoint, shared provider concurrency/RPM/TPM/daily budget, timeout, identity, and dimension checks. Backfill awaits documents sequentially, up to 500 per source family.
- Content hashes and post-provider source revalidation prevent unchanged work and delayed stale writes.
- Evidence is original ticket description, comments, and approved KB—not generated summaries/reasoning/plans. Portal tickets are excluded. Private comments require explicit policy. KB must be published and independently reviewed.
- Retrieval enforces authoritative portal/private/assignee/KB predicates before limits. Tests require that ordering. It separates ticket/comment and KB pools, caps per ticket, deduplicates, prefers authority, and reserves published KB.
- Vector succeeds-or-keyword-fallback: the signals are not fused. Cold vector queries await an external query embedding.
- Context is bounded/redacted/cited. Out-of-set citations fail. Actions come only from approved KB evidence.
- No external vector DB, Redis, broker, reranker model, or embedding worker exists. Current tests cover poisoning, scope, delayed writers, stale identity, diversification, backfill, and citations.

Unknown: corpus size, QPS, repeated-query rate, document lengths, batch contract, provider latency, DB headroom, and labelled retrieval relevance. All numbers below are bootstrap test inputs.

## Non-negotiable constraints

- One production LLM model; no second generation or reranker model and no cross-model fallback. Second agent is conditional.
- Keep pgvector unless measured post-tuning evidence proves it insufficient.
- Preserve every current authorization/provenance/portal/private/assignee/KB/citation/prompt-containment rule. Security predicates precede candidate limits and cache hits never bypass live authorization/source validation.
- Generated output never becomes retrieval evidence. Do not hold DB transactions/request sessions over provider calls. Late embeddings commit only if source state, hash, and embedding identity remain current.
- No raw query/ticket/prompt/secret/provider body in routine telemetry. Persistent vectors/caches inherit source classification.
- Prefer additive migration, flags, dual write/read, bounded backfill, reversible cutover. Separate retrieval latency from generation latency.

## Acceptance criteria

1. Decide parallel v2 store versus in-place alteration, with exact schema/index/compatibility/cleanup.
2. Fuse lexical and vector ranks deterministically without comparing raw score scales; retain separate KB capacity and diversity.
3. Define deterministic heading/paragraph chunks, size/overlap/IDs, parent provenance, replacement/delete, and citations; prevent chunk flooding.
4. Batch embedding with durable/recoverable refresh, shared admission, bounded retry, response/dimension validation, and per-item stale-write guard.
5. Reduce cold-query latency via safe query-embedding cache and/or overlap with FTS; never share one SQLAlchemy session across threads.
6. Persist/reference one immutable authorized context snapshot per job for both agents; repeat retrieval only when corpus/source/auth/embedding identity changes.
7. Prove chunks, caches, fusion, and snapshots cannot admit portal/private/cross-assignee/unapproved/stale/generated evidence.
8. Give performance and relevance gates, production-shaped benchmark/failure injection, metrics, rollback, stop conditions, retention, and reconciliation.
9. Give file-level implementation phases and explicit option ledger.

## Options to decide

| Option | Benefits | Costs/risks | Decision required |
|---|---|---|---|
| A: tune current whole-document store | Smallest change; cache query vectors, batch embeddings, tune HNSW | Long KB remains one vector; weak passages | Target or phase only |
| B: hybrid FTS + vector | Exact identifiers plus semantics; deterministic | Two searches; cold embedding; session/concurrency safety | Implement now and how |
| C: parallel chunked pgvector v2 | Additive rollback; bounded passages; better long-KB recall | Duplicate storage; backfill/divergence; dimension lock | Prefer or reject |
| D: alter v1 in place for chunks | One store | Risky uniqueness/index migration; readers assume one row/source; poor rollback | Choose only if clearly safer |
| E: external vector DB | Independent very-large-corpus scaling | New processor/network/dual-write/DR/auth/cost | Defer/reject with triggers |
| F1: deterministic RRF + authority/diversity | Auditable, fast, one-model compliant | No learned reranker | Default candidate |
| F2: same-LLM rerank | One model but extra cost/latency/injection/nondeterminism | Hurts performance | Implement/defer/reject |
| F3: separate reranker | Possible relevance gain | Violates user constraint | Reject |
| G1: local query-vector cache | Simple/private but per replica | Lower hit rate | Assess |
| G2: PostgreSQL query-vector cache | Shared, removes repeat provider calls | Sensitive vector retention/TTL/dimension | Assess |
| G3: result cache | Avoids DB search | Hard auth/corpus invalidation | Assess |
| G4: per-job context snapshot | Reuses exact evidence across agents | Needs identity/expiry | Required |

Hybrids: A+B as early phase; B+C as target; B+C+bounded query cache+snapshot; C now/E later; deterministic RRF now and conditional same-model review only if later evidence warrants.

## Bootstrap values to challenge

- Benchmark 100k chunks and scale to 1M synthetic safe chunks before external DB consideration.
- Heading/paragraph chunks target 350–500 tokens, max 600, ~50 overlap; short ticket descriptions/comments stay single chunks.
- Candidate pools: about 40 lexical + 40 vector non-KB and 12–20 each KB; fuse with RRF near `1/(60+rank)`; select 6–10 passages, max two chunks per parent/ticket.
- Embedding batch 32, contract-bounded; max two attempts with jitter and toxic-item isolation.
- Shared query-vector cache: tenant + normalized query hash + embedding identity + dimensions, no raw query, TTL 30–60 minutes. Defer result cache; require job context snapshot.
- Gates: warm retrieval p95 <250 ms; cached-query retrieval p95 <400 ms; cold embedding+retrieval p95 <2 s; ordinary index freshness p95 <60 s; zero stale/unauthorized evidence.

## Details the candidate must resolve

- v2 schema and vector-dimension lock/preflight;
- deterministic chunk IDs and atomic source replacement;
- embedding work via earlier durable `ai_jobs`, narrow lease fields/table, or another explicit mechanism;
- batch validation and item-level current-hash check;
- exact RRF/ties/diversity and security-filter ordering;
- FTS overlap with cold embedding using separate sessions;
- two-agent snapshot identity/citations;
- changes to migration/database, `ticket_vectors.py`, API/jobs, settings/Helm/docs, and tests;
- non-destructive rollback and old-store retirement.

## Verification

Use a labelled set with exact error/product IDs, paraphrases, long KB, competing comments, cross-assignee, portal/private/unapproved poison, stale updates, duplicates, and no-answer queries. Measure Recall@5/10, MRR or NDCG@10, relevant published-KB presence, duplicate-parent rate, citation/action grounding, no-answer precision, latency p50/p95/p99, query-cache hit/age, batch utilization/provider latency, index lag/retry/stale count, v1-v2 divergence, rows/query, DB CPU/IO/locks/index size, prompt tokens, and core API latency under search/backfill.

Inject provider timeout/partial/malformed batch, wrong dimension, toxic item, delayed old embedding after edit/delete/unpublish, worker death, missed wake-up, DB restart, stale query cache/snapshot, unauthorized sources, and chunk flooding. Pass only with relevance not below baseline, latency gates met, no ticketing regression, and zero unauthorized/stale evidence.

## Out of scope

Code changes in this turn; second production model; DB replacement without evidence; autonomous remediation; indexing secrets/generated/unapproved/portal/private evidence; capacity or relevance claims without benchmarks.

Each voter must cover criteria, options/hybrids, schema/algorithms/files, compatibility, failures, rollback, stop conditions, risks, unknowns, and adversarial checks. Proposal verdict `PROPOSE`, version `v0`, exact brief digest.
