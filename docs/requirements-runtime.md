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

Save completion clears only the in-memory draft version captured when that request
started. A later edit restored after navigation survives an older request finishing;
this does not cancel the earlier server write or bypass requirement revision checks.

Saved source bodies share an account-scoped query cache between reading and editing.
Because saved sources are immutable, cached bodies do not refetch on focus or reopen;
normal inactive-query eviction and sign-out cache clearing still apply. Closed
requirement editors do not initiate source-body queries.

The requirement card list initially renders 20 matches and can reveal 20 more at a
time. Search, scope filters and sorting run over the complete workspace before this
display limit is applied; BRD export continues to include all saved requirements.

### Evidence passage navigation regression

With a local synthetic source, paste an exact excerpt into **Focus on a passage**.
Close and reopen the source: the excerpt must remain. Open a different source:
its passage must be independent. Return to the first source: its excerpt must
remain. **Clear passage** must remove only that source's selection.

Before the passage-cache fix, the first close/reopen reset the textarea to empty.
The same browser sequence passed after moving passage state into the shared,
account/workspace/source-scoped tab draft cache. Cache tests additionally cover
account and initiative isolation and logout clearing. Full reload persistence is
intentionally unsupported; this check does not claim persistence across reloads.

### Shared save boundary regression

The workspace owns the decision-save flag as well as its main operation flag.
Their combined pending state gates exports, requirement actions and decision
forms. Decision saves release that flag only after the request and saved-work
refresh finish (or error handling finishes). This closes the gap left by the
initial export guard, which observed only operations started by the page.

`requirement-decision-render.test.js` checks disabled question and restored-answer
forms against the shared pending state; both checks failed before the state was
lifted into the workspace. A controlled asynchronous request additionally checks
that the decision form reports pending immediately and keeps it set until the
refresh completes. These tests cover component rendering and the save lifecycle;
they do not simulate another browser tab changing server data. Cross-requirement
AI analysis remains independent because it produces suggestions without saving
business records.

### Unicode source and evidence limits

Source import, pasted source text, selected passages and requirement evidence use
`requirementTextBounds` to count Unicode code points after trimming boundary
whitespace. They retain the supplied text rather than truncating it. Native
textarea UTF-16 length constraints are removed from these fields; the action is
disabled when the shared bounds check fails. Exact source matching remains a
separate requirement. Combining marks count separately, as they do in the API.

Against the pre-fix importer, 50,001 supplementary characters were rejected,
five emoji were accepted despite the ten-character minimum, and 100,000 ASCII
characters surrounded by spaces were rejected. The import regression test now
checks all three cases. Shared bounds tests cover the 4,000, 12,000 and 100,000
limits, short input and NUL rejection. Acceptance criteria already counted code
points. Other short text fields still use native browser length constraints;
this change does not claim to normalize every input in the application.

### File import navigation regression

An in-flight source import owns a draft-cache identity. A completed preview is
written to that cache before updating component state, so leaving the initiative
while parsing does not discard the result. Replacing or discarding the draft,
or clearing the cache on sign-out, invalidates that identity. A late result cannot
recreate a discarded draft or overwrite newer work. An import failure restores
the previous draft only when the request still owns it.

The component lifecycle test suppresses post-request render effects to reproduce
navigation/unmount: the pre-fix component failed to retain the completed preview.
The fixed test passes and also covers newer drafts, sign-out and failures with or
without an existing draft. This is tab-memory protection, not persistence across
a full browser reload; returning and editing a draft can supersede the old import.

### Browser smoke check: decision review and Unicode input

Verified against the local production build after `30dcfea`, using the synthetic
Supplier onboarding pilot (REQ-002 revision 6):

1. Open **Review the requirement**. Confirm evidence and acceptance criteria are
   followed by **Business decisions to consider** with two recorded global decisions.
2. Expand the supplier acknowledgement failure question. Its answer owner and
   recorded Operations-queue/retry rationale must be readable in the review form.
   Cancel without signing off.
3. Open **Add supporting material**. Enter a synthetic title and five emoji in
   **Source text**. The counter must show 5 and **Save source** must be disabled.
4. Append five more emoji. The counter must show 10 and saving must become available.
5. Clear both test fields without saving. The counter must return to 0, saving must
   be disabled and the unsaved-material notice must disappear. Close the form.

This sequence passed in the browser. No business record or sign-off was changed.
It verifies rendered interaction, supplementing the component and boundary tests;
it does not exercise provider analysis, file uploads or a Dev deployment.
