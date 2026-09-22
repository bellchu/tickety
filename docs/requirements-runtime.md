# Requirement workspace runtime boundaries

The [business guide](requirements-gathering.md) describes the working process.
These boundaries explain extraction, persistence and operational limits.

## Capacity and access

An initiative holds at most 50 immutable sources, 200 requirements and 200 decision
records. Each source contains at most 100,000 characters. Exact source and new
requirement reuse is checked before the corresponding capacity rejection.
Sources are compared by digest and then exact confirmed text after input trimming;
requirements compare the source and all normalized business input fields, including
ordered acceptance criteria. No fuzzy merging or cross-initiative reuse occurs.

Workspace data and history require an active operations session and are private to
the creator and active administrators. AI additionally requires an explicit request
origin; in local demo mode AI use requires an administrator. Review-capacity labels
and decision answer-owner labels do not grant authorization.

Workspace overview queries omit source bodies. Bodies are loaded when reading or
analyzing a specific source. A capacity-sized overview test covers 50 sources, 200
requirements and 200 decisions with four database reads and no material-body reads.

## Source extraction

All accepted file uploads are bounded to 400 KB. Preview must be confirmed with a
separate save. Digests cover the confirmed text, not original file bytes.

| Format | Extraction behavior and boundaries |
| --- | --- |
| TXT / Markdown / VTT / SRT | UTF-8 text, at most 100,000 characters, no NUL characters. VTT/SRT are treated as transcript text. |
| EML | MIME decoding retains subject, sender, recipients and date; prefers plain text over duplicate HTML alternatives. Attachments and attached messages are excluded. HTML becomes inert text without fetching resources. Nesting and part counts are bounded; encoding failures reject the preview. |
| DOCX | Reads the Word body part in memory: at most 2 MB decompressed body and 100,000 extracted characters, bounded XML depth and element count. Rejects entity declarations, encrypted packages and duplicate ZIP entries. Table cells use `\|`; original layout and automatic numbering are not retained. Headers, footers, images, notes and comments are excluded with warnings. Tracked insertions are included and deletions excluded with a version-confirmation warning. Macros, embedded objects and links are not run. |
| PDF | Selectable text with page markers; at most 50 pages, 2 MB decoded content per page and 100,000 output characters. Encrypted files and entirely textless PDFs are rejected. Empty pages are identified. Reading order, tables and symbols need human review; this is not OCR. |

PDF extraction uses a separate process, with at most two concurrent parsers per API
process. A parent watchdog terminates workers after ten seconds or above 256 MiB
resident memory. Linux additionally enforces a 256 MiB address-space limit; Linux
and macOS apply a five-second CPU limit. macOS memory checks are sampled, so transient
peaks can exceed the threshold before termination. All file previews check workspace access and release the database transaction
before parsing; file processing does not keep a database connection occupied.

## AI input and output

All assistance uses the configured provider, existing secret redaction,
structured-output validation and durable per-user AI budgets. Inputs are bounded;
truncation and discarded candidate counts are visible. Unavailable providers do
not produce fabricated fallback answers.

A focused passage must be an exact continuous substring of the saved source,
10–12,000 characters after input trimming. Validation occurs before reserving AI
budget. Only the passage, initiative objective and source title go through the
existing redaction and prompt limits. Neither passage nor full-source analysis
establishes complete document coverage.

Cross-review accepts 2–8 distinct requirements in the owned workspace. Each selected
reference has its own bounded, redacted input field. Output references must belong
to that selection. Responses include the input revisions; the interface disables
tracking findings if locally refreshed revisions differ. Suggestions do not mutate
requirements, merge scope or create decisions automatically.

## Agreement and audit history

Creation, editing, sign-off, story preparation and reopening by a blocking question
record before/after snapshots in the same transaction as the business change. A
failed history write prevents the change from committing. Withdrawn agreement and
stories remain inspectable in history.

History is loaded on request in pages of ten events, ordered by monotonically
increasing requirement revision rather than wall-clock time. The unique
`(requirement_id, revision)` index serves that ordering and rejects duplicate events.
Its migration preserves existing history; inconsistent duplicates fail migration
rather than being discarded. There is no history-edit or delete API. For requirements
created before history tracking, the first later change captures the previous
state; earlier actions are not reconstructed.

Revision checks reject stale edits and sign-offs. Open blocking questions prevent
agreement and story preparation; resolving them never restores sign-off. Deferred
requirements also reject sign-off, story creation and AI story refinement. Reusing
an identical newly captured requirement does not create a history event or withdraw
its current agreement. An unchanged edit also preserves the revision and history,
but still checks access, source evidence and the submitted revision first.

## Unsaved drafts

Requirement editors, material previews and decision forms use account- and
initiative-scoped tab-memory entries in the authenticated query cache. Drafts are
not written to local storage or the server. Saving or discarding clears only the
corresponding draft; sign-out clears the cache. An application-level unload warning
also covers drafts left behind while browsing other pages. Browser warning support
is browser-dependent; this is not durable autosave.
