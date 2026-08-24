# RAG v2 operations and rollout

RAG v2 is an additive, PostgreSQL/pgvector retrieval path. It keeps v1 intact
for rollback, adds deterministic chunks, fuses full-text and vector ranks with
RRF, caches only query embeddings, and binds model calls to an immutable
authorized context snapshot.

It does not add a second production LLM. Both logical agents use the configured
`DEFAULT_MODEL`; an embedding model is used only by the retrieval subsystem.

## Safety invariants

- Portal tickets never enter shared retrieval.
- Private comments require both operator opt-in for indexing and live actor
  authorization for retrieval.
- KB articles must be published and independently reviewed.
- Ticket assignee scope, source existence, and current source eligibility are
  checked before candidate limits.
- Search metadata cannot grant authority.
- Generated summaries, reasoning, answers, and plans are never indexed.
- A delayed embedding result is accepted only for the exact active lease,
  chunk/content/parent hashes, source revision, and embedding identity.
- Both agents consume the exact same snapshot evidence and citation allowlist.
  A changed authorization fingerprint, corpus generation, source hash, model
  identity, or expiry forces fresh retrieval.

## Configuration

All flags default off. `TICKET_RAG_SCOPE_KEY` and its allowlist are
deployment-owned and must never be copied from an HTTP request.

| Setting | Default | Purpose |
|---|---:|---|
| `TICKET_RAG_SCOPE_KEY` | `default` | Deployment retrieval/cache boundary |
| `TICKET_RAG_V2_SCOPE_ALLOWLIST` | `default` | Scopes eligible for v2 rollout |
| `TICKET_RAG_V2_WRITE_ENABLED` | `false` | Queue deterministic v2 chunks |
| `TICKET_RAG_V2_WORKER_ENABLED` | `false` | Run the batched embedding loop in the dedicated worker |
| `TICKET_RAG_V2_READ_ENABLED` | `false` | Serve hybrid v2 retrieval and require snapshots for analysis |
| `TICKET_RAG_EMBED_BATCH_SIZE` | `32` | Maximum provider batch size |
| `TICKET_RAG_QUERY_CACHE_TTL_SECONDS` | `2700` | Hash-keyed query-vector TTL |
| `TICKET_RAG_SNAPSHOT_TTL_SECONDS` | `86400` | Maximum context snapshot lifetime |

Chunk defaults are `cl100k_base`, target 450 tokens, maximum 600, and overlap
at most 50. Changing the tokenizer or these values changes the chunker identity
and requires a controlled reindex. Changing the embedding dimension requires a
new schema version; never alter an indexed vector dimension in place.

## Rollout

1. Run `alembic upgrade head`. Revision 0008 validates the existing v1 vector
   dimension and creates the parallel v2 tables and indexes.
2. Capture the v1 labelled relevance set and latency, provider, and database
   baselines.
3. Set write enabled for one allowlisted scope. Repeatedly call the existing
   admin backfill endpoint until `rag_v2.queued` and missing-source divergence
   are bounded. Source replacement contains no provider call.
4. Enable the v2 worker. Watch queue age/depth, batch utilization, retries,
   dead letters, provider limits, database CPU/IO/locks, and indexing freshness.
5. Shadow v2 retrieval against the labelled set. The read-only benchmark is:

   ```sh
   TICKETY_BENCH_TOKEN=... python scripts/benchmark-rag-v2.py \
     evaluation/rag-labelled.jsonl --base-url https://tickety.nexora.com
   ```

6. Enable reads for an internal/low-risk scope. Confirm snapshot creation and
   exact snapshot reuse by both logical agents before expanding the allowlist.
7. Keep v1 dual-write throughout the retention window. Retire it only under a
   separately approved change after a rollback drill.

## Promotion gates

- Recall@5/10 and MRR/NDCG@10 are not below the accepted v1 baseline.
- Warm retrieval p95 is below 250 ms; cached retrieval p95 is below 400 ms;
  cold embedding plus retrieval p95 is below 2 seconds.
- Ordinary indexing freshness p95 is below 60 seconds.
- There is zero portal, private, cross-assignee, unapproved, generated, stale,
  or citation-allowlist-bypass evidence.
- A production-shaped observed corpus plus 100,000 chunks passes. Run the
  1,000,000 safe synthetic-chunk PostgreSQL/HNSW test in an isolated staging
  database before considering external vector infrastructure.
- Provider budgets, ticketing API latency, and the database error budget remain
  within their accepted baselines.

Stop promotion on any security or freshness failure, unexplained reconciliation
loss, dimension mismatch, relevance regression, latency miss, budget overrun,
or failed rollback drill.

## Failure behavior and rollback

Embedding, cache, or vector-query failure degrades to authorized lexical
retrieval. An authoritative database check failure fails closed.

Rollback is configuration-only:

1. Set `TICKET_RAG_V2_READ_ENABLED=false` to return reads to v1 immediately.
2. Set `TICKET_RAG_V2_WORKER_ENABLED=false` to stop new claims after current
   calls finish.
3. Set `TICKET_RAG_V2_WRITE_ENABLED=false` to pause chunk replacement/backfill.

Leave the additive schema in place for diagnosis. Do not run a destructive
downgrade. Expired leases are recovered automatically; dead-letter chunks stay
available to lexical retrieval and are reported by the status endpoint.
