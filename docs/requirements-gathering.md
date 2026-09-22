# Requirements gathering for business operations

Open **Work → Requirements** to start an approved project/request or an
enhancement initiative. Initiatives are visible to their creator and active
administrators. A real operations session is required, including in demo mode.

1. Record the business objective and gather business documents, emails, SOPs,
   and meeting transcripts. Paste text or import UTF-8 TXT, Markdown, EML, VTT,
   or SRT files. The first release accepts text only; PDF and Word conversion
   are not yet available. Each source is immutable and retains a SHA-256 digest.
2. Create a requirement from an exact excerpt of a saved source. Give it a
   stakeholder, required capability, business outcome, priority, and observable
   acceptance criteria. Requirements receive stable initiative-local `REQ-001`
   identifiers. Incomplete requirements can be saved as drafts.
3. Resolve the quality-check findings, then sign off in a business capacity:
   Product Owner, Business Stakeholder, Technical Business Analyst, or DTL.
   This capacity describes the review; it does not grant application permissions.
   The signed-in reviewer, note, time, and requirement revision are recorded.
   Automated checks never replace a person's decision.
4. Create a `US-001` user story from the validated requirement. The source,
   requirement reference, validated revision, and acceptance criteria remain
   linked. Editing a requirement invalidates its sign-off and removes its
   generated story until reviewed again.
5. Export the BRD as Markdown for development handoff. It contains the business
   objective, evidence register, documented requirements, functional capability
   and acceptance criteria, outstanding clarifications, sign-off, and stories.
   No Jira tickets or external communications are created by this workflow.

Each initiative is bounded to 50 sources (100,000 characters each) and 200
requirements. Concurrent edits use revision checks; a stale editor receives a
conflict instead of silently overwriting someone else's changes.

This initial increment provides the human-controlled workflow. AI-assisted
gathering, validation suggestions, and story refinement are a subsequent
increment and must use the configured provider and existing AI request budgets.
