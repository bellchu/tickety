# Requirement workspace verification record

These are historical checks and repeatable regression scenarios for the
[requirement workspace runtime](requirements-runtime.md). Test totals and commit
references describe individual checkpoints, not a claim that every environment
has been validated. The [business guide](requirements-gathering.md) describes the
user workflow.

Local browser checks, automated tests, live-provider checks and Dev deployment are
separate evidence. Preserve the stated limitations when using these records to
plan release verification.

## Evidence passage navigation regression

With a local synthetic source, paste an exact excerpt into **Focus on a passage**.
Close and reopen the source: the excerpt must remain. Open a different source:
its passage must be independent. Return to the first source: its excerpt must
remain. **Clear passage** must remove only that source's selection.

Before the passage-cache fix, the first close/reopen reset the textarea to empty.
The same browser sequence passed after moving passage state into the shared,
account/workspace/source-scoped tab draft cache. Cache tests additionally cover
account and initiative isolation and logout clearing. Full reload persistence is
intentionally unsupported; this check does not claim persistence across reloads.

## Shared save boundary regression

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

## Unicode source and evidence limits

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
points. Business names, roles, objectives, questions, answers and sign-off notes now use
shared Unicode-aware controls backed by native custom validity. Optional draft
fields remain optional, required whitespace-only fields are rejected, and overlong
text remains available for editing. Initiative search uses the same Unicode-aware control; its query is trimmed before
submission and remains limited to 200 characters. Acceptance criteria are bounded
per entry without native UTF-16 truncation of their textareas.

## File import navigation regression

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

## Browser smoke check: decision review and Unicode input

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

## Refresh-failure delivery regression

The page shares one snapshot-availability condition across BRD export, the export
recommendation and story copying: no save in progress, no workspace refresh in
progress and no workspace query error. Failed refreshes retain readable data but
show an explicit old-snapshot notice; a successful refresh restores delivery actions.

Repeatable local check with an already loaded synthetic initiative and prepared
story: stop only its local preview API, click **Refresh**, and let the query retries
finish. Before this fix, **Export BRD** and **Copy story** were enabled despite the
service-unavailable message. After the fix both remain disabled during refresh and
after failure. Restart the same API and refresh successfully: both become available
again and the notice clears. This before/after sequence passed in the browser;
no record was changed and no file or clipboard content was exported. The story-card
test also verifies that an unavailable snapshot remains readable but not copyable.
The recommendation export uses the same guarded callback; that specific recommendation
was not displayed by the synthetic initiative during this browser check. This guard
does not detect changes made in another tab after the last successful fetch.

## Suggested decision navigation

With an open blocking question in a synthetic local initiative, switch the decision
register to **Recorded decisions** and enter a search that matches nothing. Click
**Review this business question** in the suggested focus. The register must return
to **Open questions**, clear the search and display the target with **Suggested
business question**. This sequence passed against the production build at commit
`95d3c5e`; production route verification also passed. Component tests additionally
cover a target beyond the first 20 records and preservation of another answer draft.
The browser check did not exercise the deferred-history message or a nonempty scope
filter. Its synthetic REQ-002 question remains open pending approval to record the
verification result; the attempted resolution was blocked by automatic approval.

The current-delivery filter was checked in the browser using the production build
at `2dd69dc`: the existing REQ-002 blocker appeared under **Current delivery blockers**,
then disappeared when **Decisions affecting** selected REQ-001. Returning to all
requirements restored the scope. The collapsed summary showed one current blocker
and zero deferred blockers. No business records were written. Deferred, unknown-scope
and active-answer combinations are covered by the automated filter/component tests.

## Structured acceptance criteria

Criteria remain an array through saved requirement editing, AI draft adoption,
refinement and tab-memory draft recovery. Newlines belong to an individual criterion;
they are never used to reconstruct array boundaries. Up to 20 entries can be edited,
with nonempty entries checked against the API's Unicode character and NUL limits.
Validation reports the original entry position even when earlier entries are empty.

Repeatable browser check: edit an existing synthetic requirement, add a criterion
and enter three lines. Its count must increase by one, not three. Replace that entry
with `short`: the corresponding textarea must have `aria-invalid=true` and **Save
draft** must be disabled. Replace it with a valid sentence: the error marker clears
and saving becomes available if the other fields are valid. Remove the temporary
entry and cancel. These checks passed locally without saving or changing the
original requirement. Component regressions cover editing/removing a middle entry,
retaining neighboring multiline values, the 20-entry limit and correction of errors.

Keyboard continuity and recovery check: adding an entry must focus its textarea;
removing it must focus the next entry, or the previous one when removing the last.
When no entries remain, focus returns to **Add acceptance criterion**. Ordinary
text edits must not reset focus. The component regression covers these transitions.
In the production-mode local preview, adding a second entry focused **Criterion 2**.
After entering three lines, navigating through **All initiatives** and reopening
the same initiative restored both entries with their original line boundaries.
Removing the temporary second entry focused **Criterion 1**. The editor was then
cancelled without saving; no requirement, sign-off or business decision was changed.
The production build and route verification also passed for this check.

## Evidence type filters and traceability

In the local production preview, selecting **Email** reduced the source register
from two entries to one and hid the SOP. Expanding REQ-001 and choosing **Read in
original source** reset the type filter to **All source types**, reopened the SOP,
and focused the exact highlighted quotation labelled **Evidence for REQ-001**.
This read-only check confirms evidence navigation cannot be trapped by the type
filter. The production build and route checks passed. Automated source-filter
coverage combines type, normalized title search and unlinked-only selection.

## Cross-review scope selection

In the local production preview, open **Cross-check scope**, select REQ-001,
then search for REQ-002 and select it. Searching for an unmatched phrase must show
zero matching candidates while keeping both selected requirements and their remove
controls visible. **Review selected requirements** remains enabled for the two
selected items. Removing REQ-001 from the selected list leaves one selected item
and disables review, even though neither item matches the current search.
This browser check passed; both temporary selections and the search were cleared
before closing the panel. No AI call or business write was made. Automated coverage
also verifies the submitted identifiers stay exactly equal to the retained selection.
The production build and route verification passed for this version.

## Review findings handed to decision drafts

Both single-requirement and cross-requirement findings prefill the full question,
reviewed references/revisions and AI background marked **Context to confirm**.
Component interaction tests exercise the actual tracking callbacks and verify the
scoped requirement ID. Maximum-output tests retain a 2,000-character question and
all eight reviewed references within the 4,000-character decision limit, shortening
only context with an explicit marker and preserving Unicode characters.

The production build and route checks passed. A local browser attempt using the
two synthetic supplier requirements returned **AI is unavailable**. The selected
scope remained visible and editable, and the panel allowed retry after provider
configuration. Both temporary selections were removed before closing the panel.
No generated finding or decision draft was produced by this attempt, so live
provider-to-form handoff remains unverified; component tests do not replace that
check. No business decision was saved.

## Human review of background context

**Keep as background** records an explicit actor and timestamp on source metadata.
**Revisit source** clears that marker. Both actions preserve the immutable content,
digest, requirement revisions, signed-off stories and existing questions. Repeating
the same mark retains its original attribution; exact source reimports retain it.
The suggested next action skips reviewed unlinked context, while a workspace with
only reviewed context invites capture of a business need rather than claiming it
is ready for delivery. The BRD records the context review attribution.

Migration `0045` adds nullable fields, leaving existing sources unreviewed. Adding
these fields initially broke the existing `0021` demo-bootstrap upgrade tests:
`0041` rejected the known forward columns as a partial schema. The causal invariant
is that a complete compatible bootstrap remains adoptable, while unknown or
incompatible schemas remain rejected. `0041` now accepts only the exact additional
context-field pair; `0045` validates any existing field types and nullability before
adoption. Adjacent decision/history migrations add no changed fields and remain
strict. Both original failing bootstrap tests pass, along with fresh-schema drift,
existing-evidence preservation and incompatible-context-column rejection tests.

The full backend suite passed 860 tests (two skips); the final requirement/migration
suite passed 88 tests after the recorder field was aligned with unrestricted user
ID storage. Frontend tests passed 282 cases, including contextual focus and export.
The local preview was backed up and upgraded to `0045`; all three original source
texts and digests matched the backup and all review markers remained empty. Browser
inspection confirmed the background action on the unlinked email and preserved
REQ-001's delivery-ready state. No source was marked through the browser; write,
undo, privacy and idempotency behavior is covered by isolated API tests. This is
local SQLite evidence, not a PostgreSQL Dev rollout or live marking acceptance.

Source-context marking now reads and returns the same metadata projection used by
the workspace summary. It does not fetch or transmit the immutable source body.
A 100,000-character source regression failed before this change and passes after
it: SQL capture excludes the content column and the marking response stays below
1,000 bytes. The full requirement suite passes 51 tests, including reversible
marking, source reuse, privacy and preservation of signed-off delivery content.

## Evidence exploration views

Local browser checks passed for **Show evidence**: **Needs exploration** displayed
only the unlinked, unreviewed email; **Kept as background** showed zero results
because no sources had been marked. From that empty view, **Read in original source**
on REQ-001 restored **All evidence** and focused its exact highlighted SOP excerpt.
Combining **Needs exploration**, source type **SOP** and title search `supplier`
produced zero results as expected. **Show all evidence** then cleared the title,
type and review filters together. No source classification or business record was
changed during these checks. Build and production-route verification also passed.

## Repeated quotation navigation

A separate local SQLite fixture contained two exact copies of REQ-001's quotation,
one below a current-procedure heading and one below an earlier-correspondence
heading. The production-mode browser showed the duplicate warning and disabled
**Previous occurrence** at the first match. **Next occurrence** moved the highlight
to the second context, focused **Evidence for REQ-001**, kept it visible, and disabled
further forward navigation. Moving back restored the first location with the whole
source text intact. Enter-key activation also moved to the second match correctly.
The isolated tab and both temporary services were closed afterward. The main preview
was updated and retained its original source texts/digests and requirement statuses.
No business records in the main preview were changed. Build and route checks passed.

## Priority guidance and source disclosure

The production build at `e1f0d67` passed build and production-route checks. In the
local supplier pilot, the existing blocking decision remained the suggested focus.
The SOP card exposed **Read source text** with a collapsed accessibility state;
clicking it displayed the saved text and changed the state to expanded with
**Hide source text**. Enter-key activation collapsed it again. These browser checks
were read-only. Cross-stage priority combinations are covered by the 287 passing
frontend tests, including a signed-off must-have preceding an unclear could-have,
same-priority clarification, and preservation of recorded blocking gates. They were
not separately exercised against new browser records in this check. Typecheck and
lint also passed. This verifies the local preview, not a Dev deployment.

## Full compatibility check after source-draft protection

At `a4ae67c`, the complete backend unittest discovery finished successfully:
861 tests run, 2 skipped. This covers the current source-summary and context-review
implementation as well as the existing migration checks; it does not establish a
successful Dev rollout or live AI-provider operation. The frontend suite passed
289 tests with typecheck and lint in the implementation phase.

The source form memoizes Unicode bounds by content, so title and type edits do not
recount the full body. A local Node microbenchmark of 500 validations after warm-up
measured about 0.22 ms for 100,000 ASCII characters and 0.46 ms for 100,000 emoji
code points per validation. These are helper timings, not browser interaction or
end-to-end import measurements. No optimization was justified by that result.

## Empty requirement view recovery

The local production preview was filtered by a nonmatching search, **Not this time**
and the unlinked supplier email. **Show all requirements** reset search, readiness
and source together, restoring REQ-001 and REQ-002. The action only changes view
state; it does not invoke editor transitions or write business records. Build,
production-route verification, typecheck and lint passed for this change.

## Source replacement browser check

On the production preview containing `a4ae67c`, an unsaved synthetic title and body
were entered in the source form. Selecting a local TXT file opened **Replace unsaved
source material?** with **Keep editing** initially focused. Cancelling preserved
both fields. Selecting the same file again and confirming replaced the preview
with its filename and text, leaving **Save source** as a separate action. The
synthetic fields were then cleared and the form closed; no source was saved and
no existing business record was changed. Failure retention, late completion and
sign-out behavior remain covered by the component lifecycle tests.

## Shared-label integration build

The production build at `326cee4` passed build and route verification after the
sign-off provenance and evidence-export changes. The refreshed local supplier
workspace loaded with its Enhancement label, two requirements, one prepared story
and the existing blocking question still first in suggested focus. No business
records were written. Export disposition and shared source names are covered by
the 291-test frontend suite; this browser check only establishes page integration.
The build has not been pushed or deployed to Dev.
