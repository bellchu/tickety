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

- Record the business objective and gather business documents, emails, SOPs,
   and meeting transcripts. Paste text or import UTF-8 TXT, Markdown, EML, VTT,
   or SRT files. The first release accepts text only; PDF and Word conversion
   are not yet available. Each source is immutable and retains a SHA-256 digest.
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
