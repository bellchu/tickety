# Requirements gathering for business operations

Open **Work → Requirements** to start an approved project/request or an
enhancement initiative. Initiatives are visible to their creator and active
administrators. A real operations session is required, including in demo mode.

The workspace keeps evidence, business decisions, and delivery stories together.
Its suggested focus responds to missing evidence, unresolved quality findings,
reviewable drafts, new sources, and agreed work awaiting a story. These are
contextual recommendations; users can revisit any material. Search and readiness
filters help focus attention without forcing everyone through numbered stages.
Human sign-off and evidence requirements remain enforced by the backend.
Opening an initiative gives it a bookmarkable `?initiative=` address. Refresh and
browser history preserve the selected initiative; the address does not grant
access to users who cannot already view it.

- Record the business objective and gather business documents, emails, SOPs,
   and meeting transcripts. Paste text or import UTF-8 TXT, Markdown, VTT, or SRT files. EML
   import decodes MIME email headers and body into a reviewable text preview. DOCX import extracts document body text and table rows. PDF import extracts selectable text with page markers. Scanned documents
   need OCR or transcription first; older DOC files are not supported. Each source is immutable and retains a SHA-256 digest.
- Create a requirement from an exact excerpt of a saved source. Give it a
   stakeholder, required capability, business outcome, priority, and observable
   acceptance criteria. Requirements receive stable initiative-local `REQ-001`
   identifiers. Incomplete requirements can be saved as drafts.
- Resolve the quality-check findings, then sign off in a business capacity:
   Product Owner, Business Stakeholder, Technical Business Analyst, or DTL.
   This capacity describes the review; it does not grant application permissions.
   The signed-in reviewer, note, time, and requirement revision are recorded.
   Automated checks never replace a person's decision.
- Create a `US-001` user story from the validated requirement. The source,
   requirement reference, validated revision, and acceptance criteria remain
   linked. Editing a requirement invalidates its sign-off and removes its
   generated story until reviewed again.
- Export the BRD as Markdown for development handoff. It contains the business
   objective, evidence register, documented requirements, functional capability
   and acceptance criteria, outstanding clarifications, sign-off, and stories.
   No Jira tickets or external communications are created by this workflow.

Each initiative is bounded to 50 sources (100,000 characters each) and 200
requirements. Concurrent edits use revision checks; a stale editor receives a
conflict instead of silently overwriting someone else's changes.

## AI assistance

AI gather analyzes one selected source and proposes up to eight requirements with
exact source excerpts. Candidates with unverifiable excerpts are excluded. The
interface discloses truncated sources, discarded candidates, assumptions, and
stakeholder questions. Review a candidate in the editable requirement form
before saving it; nothing is automatically added or signed off.

AI review checks ambiguity, testability, missing context, scope, and traceability.
AI story refinement proposes clearer wording and acceptance criteria after sign-off.
Accepting a refinement opens a revised draft, so changes require human review again.

All three actions use the configured provider, existing secret redaction,
structured-output validation, and durable per-user AI budgets. No synthetic
responses are presented when a provider is unavailable. Real sessions and explicit
request origins are required; local demo AI additionally requires an administrator.
Source bodies are loaded only when reading or analyzing that source, not with every
workspace overview refresh.

## Questions and decisions

Track stakeholder questions and assumptions in the decision log, including an
answer owner and either one affected requirement or the whole initiative.
AI gathering and review questions can be copied into this log for human review.
The owner is a follow-up label, not an access grant or automated notification.

Blocking questions reopen affected requirements, withdraw their generated stories,
and prevent sign-off until answered. Initiative-wide blockers also apply to future
requirements. Exploratory questions do not block agreement. An answer records the
signed-in author, time, and rationale; it cannot overwrite a prior resolution.
Changed circumstances require a new question. Resolving a blocker never restores
sign-off automatically: revise the scope if needed, then obtain a fresh review.
The BRD includes open questions and recorded decisions. Each workspace holds at
most 200 decision records.

EML previews are bounded to 400 KB and 100,000 extracted characters, with MIME
nesting and part-count limits. They retain subject, sender, recipients and date,
prefer plain text over duplicate HTML alternatives, and exclude attachments and
attached messages. HTML is converted to inert text without fetching resources.
Encoding failures reject the preview instead of silently replacing characters.
Review conversion warnings and the text before saving. Previewing does not store
an evidence source or call an AI provider; the saved evidence digest covers the
confirmed text, not the original EML bytes.

DOCX preview uses the same explicit review-and-save flow. It reads only the Word
body part in memory, with a 400 KB package limit, a 2 MB decompressed body limit,
100,000 extracted characters, and bounded XML depth and element count. It rejects
entity declarations, encrypted packages and duplicate ZIP entries. Table cells
are separated with `|`; original layout and automatic numbering are not retained.
Headers, footers, images, notes and comments are excluded with a visible warning.
Tracked insertions are included and deletions excluded; their presence produces
a version-confirmation warning. No macros, embedded objects or links are run.

## Delivery scope

The **Not this time** priority preserves a requirement for future consideration.
It stays searchable and has its own filter, but is excluded from current review
and delivery suggestions. Questions tied only to deferred requirements do not
supersede actionable work in the suggested focus; initiative-wide blockers remain
relevant. Sign-off, story creation and AI story refinement reject deferred scope.
Changing its priority back to Must/Should/Could reopens the normal review path.
Changing any agreed requirement to Not this time withdraws its current agreement
and story through the same revision mechanism. BRD exports retain deferred needs
and evidence, clearly label their scope, and exclude their stories from handoff.

PDF preview runs in a separate process: at most two concurrent parsers per API
process, 50 pages, 400 KB input, 2 MB decoded content per page and 100,000 output
characters. A parent watchdog terminates workers after ten seconds or above
256 MiB resident memory; Linux additionally enforces a 256 MiB address-space
limit, and both Linux/macOS apply a five-second CPU limit. macOS memory checking
is sampled, so transient peaks can exceed the threshold before termination.
Encrypted files are rejected. Pages without extractable text are listed explicitly,
and all-empty PDFs are rejected rather than silently creating empty evidence.
This is text extraction, not OCR; reading order, tables and symbols need review.

## Requirement history

Each requirement has a read-only History view with before/after values, action,
revision, actor and time. Creation, editing, sign-off, story preparation and
reopening by a blocking question are recorded in the same database transaction
as the business change. A failed history write prevents the change from committing.
Older sign-offs and stories therefore remain inspectable after current agreement
is withdrawn. History is private to the same workspace access boundary and loaded
only on request in pages of ten events. There is no history-edit or delete API.
For requirements created before this feature, the first later change captures
its previous state; earlier actions are not invented or backfilled. Earlier wording
can be copied into a new edit, which still requires fresh sign-off.

Reimporting identical confirmed text into the same initiative reuses the existing
source, including its original title, type and evidence links. The interface names
the reused source and opens it for inspection. This also works at the 50-source
limit. Changed text creates a separate immutable version; matching text in another
initiative remains a separate private source. Matching uses a digest followed by
an exact text comparison after normal input trimming; it does not merge similar
wording or silently replace earlier evidence.

History is ordered by the requirement's monotonically increasing revision rather
than wall-clock timestamps. A unique `(requirement_id, revision)` index both serves
this ordering and rejects duplicate revision events. Existing history is preserved
by the index migration; inconsistent duplicate data makes the migration fail
rather than silently discarding audit evidence.

For long sources, expand the saved text and select or paste a continuous passage
into **Focus on a passage**. The server verifies it matches the immutable source
before reserving AI budget. Only that passage (plus initiative objective and source
title) is sent through the existing redaction and prompt limits. Suggestions are
labelled as passage-scoped and retain the original source link. Invalid passages
never reach the provider. Explore later sections separately when a full-source
analysis was truncated; neither mode claims complete document coverage.

## Cross-requirement review

Choose 2–8 requirements in **Cross-check scope** to ask the configured AI provider
about contradictions, overlap, dependencies and scope gaps. Each selected item
has its own bounded, redacted input field so long items do not replace the other
selected references. Findings may cite only selected references and include the
reviewed revision numbers. The interface warns about partial input and disables
tracking findings if locally refreshed requirement revisions have changed.
A finding can prefill a question in the decision log; the user still confirms its
answer owner, affected scope and whether it blocks sign-off. Multi-requirement
findings default to initiative scope for that confirmation. No findings are saved,
merged, signed off or treated as proof of consistency automatically.
