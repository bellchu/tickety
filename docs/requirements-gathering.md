# Requirements gathering for business operations

Open **Work → Requirements** and create an approved project/request or enhancement
initiative with a concrete business objective. A real, active operations session
is required, including in demo mode. An initiative is visible to its creator and
active administrators. Its bookmarkable `?initiative=` address does not grant access.

## Choose the next useful action

The workspace connects evidence, business questions, agreed requirements and
stories. **Worth your attention** recommends work from the current state, including
missing material, blocking questions, incomplete drafts, reviewable requirements
and agreed work awaiting a story. It is guidance, not a sequence of mandatory screens.
Search and the readiness filters let you return to any part of the work.

| What you know now | Useful action | What must remain explicit |
| --- | --- | --- |
| The outcome is unclear | State the business objective and raise a stakeholder question | Who should answer and which scope is affected |
| A document describes the need | Save the relevant material, then capture a requirement from an exact excerpt | The source and the observable business outcome |
| Requirements may conflict | Cross-check selected requirements and track a finding for discussion | AI findings are suggestions, not decisions |
| A decision is still needed | Record a blocking or exploratory question | Whether agreement must wait for the answer |
| The scope is understood | Review quality findings and obtain human sign-off | Reviewer, review capacity, rationale and revision |
| Agreed work is ready for delivery | Prepare a story, copy it or export the BRD | Traceability and any remaining exploratory questions |
| A need belongs to a later phase | Set priority to **Not this time** | Keep its evidence without presenting it as delivery ready |

For example, a supplier SOP might require acknowledgement within thirty seconds,
while an interview leaves failure ownership unclear. Capture the acknowledgement
requirement and track the ownership question. If the answer is necessary to agree
that requirement, make it blocking and link it to that requirement. Record the
answer, revise the acceptance criteria if needed, and obtain sign-off. A later
email can add evidence and reopen discussion without restarting the whole initiative.
If it changes agreed scope, edit the requirement and review the new revision.

## Bring evidence into the workspace

Paste text or import UTF-8 TXT, Markdown, VTT or SRT; EML emails; DOCX documents;
or PDFs with selectable text. Preview and review the conversion before choosing
**Save source**. Previewing neither saves an evidence source nor calls AI.
Scanned PDFs need OCR or transcription first; older DOC files are not supported.
Review warnings about missing images, formatting, tables or tracked changes.
A failed import leaves the existing material draft and its conversion warnings
intact. Successful imports replace the preview and set the type for the new file.

Saved sources are immutable. Their SHA-256 digest identifies the confirmed text,
not the original uploaded file. Changed text becomes a separate source. Reimporting
identical confirmed text into the same initiative reuses the original source,
including its title, type and requirement links, even at the source limit. Similar
wording is not merged; another initiative has its own private sources.

## Shape and review a requirement

Each requirement links to one exact excerpt from a saved source. Add a stakeholder,
capability, business outcome, priority and observable acceptance criteria. Incomplete
work can be saved as a draft with a stable initiative-local reference such as
`REQ-001`. Quality checks flag missing detail, vague wording and duplicate criteria.
The editor accepts up to 20 criteria, one per line, with 10–1,000 characters each;
it identifies invalid lines before saving. Empty criteria remain allowed for drafts.

Saving a new requirement whose source and all business fields exactly match an
existing one reuses that record. The interface names it; its sign-off, story and
history remain intact. This works at the 200-requirement limit. Different fields,
criteria, priorities or initiative scope remain separate requirements. This reuse
applies to new capture, not to edits of an existing record.

Sign-off requires complete quality checks, no applicable open blocking questions,
and active delivery scope. Review capacity can be Product Owner, Business Stakeholder,
Technical Business Analyst or DTL; this label does not grant application permissions.
The signed-in reviewer, note, time and revision are recorded. Automated checks and
AI never replace that person's decision.

Saving changed business content withdraws its current sign-off and story. Saving
without changes preserves agreement, story and revision. Concurrent edits
use revision checks: stale work receives a conflict instead of overwriting newer
changes. Use **History** to compare earlier wording, agreement and stories. Each revision
summarizes changed business fields, scope changes and withdrawn agreement or stories
before you expand the detailed comparison. Copying
old wording into a new edit still requires fresh sign-off; history itself is read-only.

## Resolve business questions

A question records an answer owner and either one affected requirement or the whole
initiative. The owner is a follow-up label, not a notification or access grant.
Submitting an identical open question with the same owner, scope and blocking status
reuses the existing record without reopening requirements again. Resolved questions
can be raised anew when circumstances change.

A blocking question reopens affected requirements, withdraws their stories and
prevents sign-off until answered. Initiative-wide blockers also apply to future
requirements. Exploratory questions do not block agreement. Recording an answer
retains its author, time and rationale; an earlier resolution cannot be overwritten.
Changed circumstances require a new question. Answering a blocker does not restore
sign-off automatically: update the requirement if needed and obtain a fresh review.

Filter the register to open, blocking, exploratory or recorded decisions, and search
by question, answer owner or resolution. An answer being edited stays visible across
filters. Questions linked to deferred requirements display **Not this time**.

AI questions, review findings and story-refinement assumptions can prefill the log
for human review. Questions from an existing requirement retain that scope; source
exploration starts at initiative scope. Choose the owner, affected scope
and blocking status before saving. Replacing an unfinished question, or switching
away from an unfinished answer, asks whether to keep or discard the draft.

Requirement search includes the stakeholder, outcome, evidence excerpt, acceptance
criteria and prepared story, including its reference. Wrapped text is searchable as
a continuous phrase. Search combines with the selected readiness or deferred-scope
view; it does not change delivery eligibility. Choose **Business priority** to discuss
must-have needs first, followed by should-have, could-have and deferred needs. Equal
priorities retain their recorded order. Return to **Recorded order** at any time;
sorting does not update priorities or saved records. Suggested focus also uses recorded
priority when choosing among reviewable requirements or signed-off requirements
awaiting a story. Blocking questions and unclear requirements still take precedence.

While reading a saved source, select or paste an exact 10–4,000-character passage
and choose **Draft a requirement from this passage**. The draft carries the source
and excerpt; describe the stakeholder, business outcome and acceptance criteria
before saving. This action is available without AI and protects existing unsaved
edits before replacing them.

The sign-off form displays the exact revision being reviewed, its priority, business
outcome, acceptance criteria and evidence excerpt. Compare those commitments with
the source before recording your review capacity and confirmation note. When a
refresh reveals a changed revision, signing is disabled until you choose **Review
current version**; your note is retained for you to reassess. Newly blocked, deferred
or already signed requirements remain unavailable for sign-off. The server also
checks the revision and business gates when the request arrives.

## Use AI where it helps

- **Explore with AI** proposes up to eight requirements from one source. Unverifiable
  excerpts are excluded. Review assumptions, questions and truncation notices before
  adopting a candidate. No requirement is saved automatically.
- **Focus on a passage** analyzes a continuous exact passage from a long source.
  Select or paste it from the saved text. Invalid passages never reach the provider;
  passage suggestions keep the original source link. Explore other sections separately.
- **Get AI perspective** checks ambiguity, testability, missing context, scope and
  traceability for one requirement.
- **Cross-check scope** reviews 2–8 selected requirements for conflicts, overlap,
  dependencies and gaps. Findings cite selected references and reviewed revisions.
  After a refresh reveals changed revisions, rerun the cross-check before tracking
  findings. Multi-requirement findings initially suggest initiative-wide question
  scope; confirm whether that is appropriate.
- Story refinement proposes alternate wording after sign-off. Adopting it opens a
  revised draft, so saving it requires another human sign-off before delivery.

AI suggestions are not proof of completeness or consistency. All assistance uses
the configured provider, redaction and per-user budgets. Provider failures or budget
limits leave manual work available; the product does not substitute synthetic answers.

## Move between tasks without losing drafts

Unsaved requirement edits, sign-off notes, material text and decision drafts are kept
in the current tab's memory, separately by account and initiative. Side navigation,
**All initiatives** and browser history can leave the workspace; returning restores
that work. Saving or explicitly discarding clears the corresponding draft. Replacing
an active requirement editor asks before discarding changes.

This is not a server save or persistent browser storage. Refreshing or closing the
page loses these drafts if you proceed past the browser warning. Signing out clears
them. Save important work before leaving the session. File selection and an extraction
still in progress are not recovered; completed preview text is retained.

If a save's outcome is uncertain after a network error, use the workspace **Refresh**
button to check saved records before retrying. That refresh retains the editor; a
full browser reload does not. Restored edits retain their original revision checks.
If another person has already resolved a question, unsubmitted answer notes remain
available to copy or discard rather than overwriting the recorded decision.

## Keep delivery scope and traceability clear

**Not this time** preserves future needs and their evidence. They remain searchable
and appear in BRD exports, but cannot be signed off or produce delivery stories.
Changing an agreed requirement to this priority withdraws its agreement and story;
changing back to Must/Should/Could reopens review. Questions linked only to deferred
needs do not displace actionable work in the suggested focus; initiative-wide
blockers remain relevant.

Prepare a `US-001` story from a signed-off requirement. **Copy story** provides Markdown
with acceptance criteria, objective, initiative and requirement references, signed
revision, source excerpt and digest, reviewer details and relevant open questions.
It also carries recorded decisions for the requirement and the whole initiative,
including the answer owner, resolution, recorder and time. This preserves the
business rationale behind scope and exception handling for the delivery team.
Unrelated decisions and deferred or unsigned stories are excluded.

**Export BRD** opens with scope and readiness counts so recipients can distinguish
drafts, signed-off requirements awaiting stories, prepared stories and deferred
needs. The evidence register lists the requirements supported by each source, marks
deferred links and retains unlinked background material. It includes the objective,
requirements, capabilities,
acceptance criteria, clarifications, decisions, sign-offs and eligible stories. Copy
and export do not create Jira tickets or send messages to a delivery system.

See [runtime boundaries](requirements-runtime.md) for import limits, audit behavior,
AI admission and capacity constraints.

When a save conflicts with newer server work, the workspace refreshes its saved
data without discarding your draft. An outdated requirement editor shows both
revision numbers and offers change history plus **Load latest saved version**. Copy
useful wording before loading; replacing unsaved edits requires confirmation.
Review the updated version or decision before trying again; the application does not automatically replay the failed write.

Single-requirement AI reviews and story refinements retain their analyzed revision.
When refreshed data reveals a newer version, suggestions remain readable but cannot
be tracked or applied. Use **Analyze current version** to replace them; story
refinement requires the current requirement to be in scope and signed off.

Use **View linked requirements** on a source to inspect the needs captured from
that material, including deferred needs. The source selector combines with search
and readiness filters. **Show all sources** removes only the source restriction;
exports and initiative-wide readiness still cover the complete saved workspace.

**Related decisions** on a requirement opens its decision register scope. This
includes whole-initiative decisions as well as those linked to that requirement.
Use the status filter to inspect recorded answers or outstanding questions; an
answer currently being edited remains visible when the scope changes.

Long decision registers initially display 20 matching records. **Show more records**
expands the list; searches always cover the full register. An answer being edited
remains visible even outside the displayed batch, and filtering never clears its draft.

The BRD readiness summary separates blocking questions linked only to deferred
requirements from those affecting current scope. Questions with unavailable scope
remain counted as needing scope confirmation; the complete decision register and
overall blocker count remain in the brief.

Use **Agreed · needs a story** to find signed-off, in-scope requirements awaiting
story preparation. The view excludes requirements with blocking questions and
works with source search and business-priority ordering. Creating a story moves
the requirement into **Delivery ready**; editing it returns it to human review.

Selected evidence passages remain in tab memory when you close a material or
browse another initiative. Each material has its own passage; **Clear passage**
removes it. These selections are not saved to the server or browser storage and
are cleared by a full reload or sign-out.

History shows the range of records currently displayed. **Latest changes** returns
to the newest entries from any older page. When refreshed workspace data reveals
a new requirement revision, the history panel starts at the latest entries.

The initiative list shows total captured requirements, in-scope drafts awaiting
agreement, and prepared stories. Deferred needs remain in the total but do not
inflate the active draft or story counts. Prepared stories still require delivery
review; these counts are a progress overview, not a release approval.

Search initiatives by name or business objective from the overview. Submit the
search to inspect all matching initiatives you can access, including those beyond
the current page. Search text is treated literally; clearing it restores the full
list and returns to the first page.
The overview also identifies signed-off requirements still awaiting story
preparation and deferred needs, so these do not disappear between the draft and
prepared-story counts. All counts come from one grouped query per overview page.
