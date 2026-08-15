debate-protocol: 2
debate-scope: direct
debate-version: v0

# Tickety UI organization plan

## Recommended direction

Organize Tickety around a small set of repeated page types instead of redesigning each route independently:

1. Group the sidebar by work domain while keeping every destination directly visible.
2. Use one canonical page sequence, with summaries optional rather than mandatory.
3. Make the work list or activity stream the dominant region; move infrequent filters, audit data, and advisory intelligence behind clear secondary controls.
4. Rebuild the ticket detail as an activity pane plus properties rail on genuinely wide screens.
5. Introduce shared layout primitives first, then migrate routes in reversible phases.

This preserves the current routes, permissions, demo restrictions, API contracts, error behavior, brand palette, and mobile drawer. It is an information-hierarchy change, not a rebrand or backend project.

## 1. What the current UI gets right—and what should change

Preserve the dark branded shell, clear primary actions, generous whitespace, explicit loading/error/empty states, responsive card versions of dense tables, and role-aware navigation.

Change the hierarchy where the same visual weight is currently given to items with very different operational value:

- The 12-item flat sidebar is difficult to scan and omits My Time even though that route exists.
- Page headers use inconsistent title fonts, action alignment, borders, widths, and spacing.
- Dashboard repeats the same operational counts in the dark pulse and the four cards before showing the queue.
- Tickets uses a separate Saved Views card plus a tall filter card, so controls displace the actual tickets.
- Ticket detail gives editable properties, Conversation, Audit, and multiple AI sections equal full-width weight in a long vertical stack.
- Register pages repeat a four-card summary even when the values are zero or visible in the register immediately below.
- Settings can become a long unindexed form, while Reports and Intelligence lack a consistent hierarchy from urgent/actionable to contextual.

The organizing rule is: **urgency first, primary task second, context third, administration last**. Consistency comes from shared anatomy and page families, not from forcing every route to show four metrics and a table.

## 2. Global navigation

Keep the existing 256-pixel desktop sidebar, the mobile drawer, active-route behavior, focus management, and current authorization checks. Replace the single `Workspace` list with visible, non-collapsible groups in this exact order:

| Group | Destinations, in order |
| --- | --- |
| Overview | Dashboard |
| Work | Tickets, My Time |
| Service management | Services, Problems, Changes, Assets, Knowledge Base |
| People | Agents, Surveys, Leaderboard |
| Insights | Reports, Intelligence |

Keep Profile and Settings in the existing bottom utility area. Profile is always the account entry. Settings remains last and appears only under its current authorization/demo rules. Agents and Intelligence retain their existing role gates. Ticket detail remains a child of Tickets and never becomes a sidebar item.

Group labels are semantic, non-clickable text. Links remain directly visible; do not introduce collapsible groups, personalization, favorites, or a command palette in the first rollout. The sidebar may scroll at short heights, but the bottom account area remains reachable and must not overlap the link list.

My Time is placed under Work because it records effort against tickets. This is deliberately reversible: if production research shows it is used only from ticket context, its single navigation entry can later be removed without changing the page system.

## 3. Canonical page anatomy

Use this sequence unless a declared page family below overrides it:

1. **Page header** — eyebrow/icon, route title, one-line purpose or scope, and actions. Show one primary action; keep one secondary action visible when frequent, and place additional actions in a labeled overflow menu.
2. **Context alerts** — only present for permission, sync, partial-data, destructive, or service states that require attention. Do not reserve empty space.
3. **Actionable summary** — optional. Show one to four signals only when they change a decision, open a filtered view, or explain the state of the content below.
4. **Primary controls and content** — search/filter/sort immediately adjacent to the register, library, activity stream, or chart it controls.
5. **Secondary insight/help** — advisory intelligence, audit history, guidance, or explanatory material after the primary task or behind a labeled secondary view.

### Page families

- **Overview:** Dashboard.
- **Register/library:** Tickets, Services, Problems, Changes, Assets, Knowledge Base, Agents, Surveys, and My Time.
- **Record detail:** Ticket detail; its primitives can later support other record details.
- **Analytics:** Reports, Intelligence, and Leaderboard, with ranked-list semantics for Leaderboard.
- **Settings:** Settings with local section navigation and a dirty-state action bar.

### Shared frontend primitives

Build these by composing the existing Button, Badge, Alert, Dialog, EmptyState, ErrorState, Skeleton, SearchableSelect, responsive table/card patterns, and current tokens:

- `PageFrame`: standard gutter, maximum width, and `default`/`wide` density variants.
- `PageHeader`: consistent eyebrow, title, description, and action slots.
- `ContextAlertRegion`: consistent placement for global and partial-data messages.
- `SummaryStrip`: optional, linkable metrics with a compact responsive treatment.
- `SectionHeader`: title, result count/status, short help, and actions.
- `DataToolbar`: saved view, search, frequent filters, `More filters`, sort, and applied-filter chips.
- `RegisterSurface`: shared desktop table, narrow-screen card list, pagination, and loading/error/empty regions.
- `DetailHero`, `ActivityPane`, `PropertiesRail`, and `SecondaryPanel`: record-detail hierarchy.
- `SettingsNav` and `DirtyActionBar`: anchors/section selector plus Save/Cancel state.

Use the existing serif display face for top-level route titles only; use sans serif for record titles, section headings, tables, controls, and dense operational text. That keeps the current brand character while removing today’s route-to-route inconsistency. Keep radii, borders, shadows, and spacing tokenized; route files should not invent new card treatments.

## 4. Page-by-page arrangement

### Dashboard

Top to bottom:

1. `PageHeader`: Dashboard/Operations Overview, workspace and refresh context, `New ticket` when permitted, then Export as the secondary action.
2. Context alerts for sampled, unavailable, or stale signals.
3. A compact Operational Pulse strip with at most three nonduplicated signals drawn from data already loaded by the page. Make each signal link to the relevant filtered work when a safe route exists.
4. Priority Queue as the first large content region. At `xl` width, the queue occupies roughly two thirds and the current recommended-next-action card occupies one third. Below `xl`, the recommendation follows the queue.
5. A supporting SummaryStrip for service/SLA health only when those values are not already in the Pulse. Omit zero-value or repeated cards instead of filling a four-card grid for symmetry.
6. Optional advisory explanation last, clearly labeled as human-reviewed guidance.

The queue—not decorative metrics—should begin within the first desktop viewport. Loading, unavailable-intelligence, deterministic-ranking, and empty-queue paths retain their current explanations.

### Ticket Queue

Top to bottom:

1. `PageHeader`: Tickets, short result context, primary `New ticket`, and Export/Fetch as the permitted secondary action.
2. Context alerts.
3. One compact queue-control surface, replacing the separate Saved Views card and tall filter card:
   - Row 1: Saved View chips/select and `Save current`; the selected view is unambiguous.
   - Row 2 on desktop: full-width search, frequent Status control, Sort, and a labeled `More filters` button.
   - `More filters`: Priority, Category, Assignee, Rows per page, and any later secondary filter in an accessible popover on desktop and drawer on mobile.
   - Applied hidden filters appear as removable chips with `Clear all`.
4. Result count and bulk-action region. The bulk bar appears only after selection and must not cause the table to jump unpredictably.
5. RegisterSurface:
   - Identity column: subject first; ID and category as supporting text.
   - Requester.
   - Urgency: priority and status.
   - Owner.
   - Updated.
   - Row selection and a labeled overflow action; destructive actions are never hover-only.
6. Pagination at the bottom. Preserve URL/query and browser-back behavior for all view, filter, sort, and page state.

On narrow screens, use the existing card pattern: subject, priority/status, owner, and updated are visible; requester/category move to supporting details. The mobile filter drawer closes only on Apply or Cancel and returns focus to its trigger. Distinguish `No tickets` from `No matches`; the latter offers Clear filters without implying data was deleted.

### Ticket Detail

Top to bottom:

1. Compact breadcrumb back to Tickets with the ticket identifier.
2. `DetailHero`: title, ID/type/created metadata, priority/status, concise description, requester/customer context, and source-record link. Avoid repeating Created or sentiment in multiple blocks.
3. At `xl`/1280 pixels and wider, use a two-column workbench:
   - **Left, about two thirds:** Activity with Conversation as the default. Put the reply/private-note composer before the history. The existing suggested response belongs beside the composer as an explicit `Insert suggestion` or review action, not as a detached full-width card.
   - **Right, about one third:** sticky PropertiesRail ordered by operational frequency: Status, Priority, Assignee, Due/SLA, Tags, then Reporter, Category, sentiment/mood, and other read-only metadata. A single Save changes action stays visible when fields are dirty.
4. Intelligence and Audit become labeled secondary views after Activity on desktop or accessible in-page tabs within the left pane. Intelligence retains on-demand execution, provenance, synthetic labeling, failure recovery, and advisory wording. Audit never competes with Conversation in the first screen.
5. Recognition/points appears as compact resolution metadata near the resolved state, not as a separate major section.

At 1024–1279 pixels, retain the desktop sidebar but use a single-column ticket page because the remaining main pane is not wide enough for a useful rail. Below 1024 pixels the navigation is a drawer. The single-column content order is Hero and actions → essential properties → Conversation → remaining-properties disclosure → Intelligence → Audit. Use the same DOM order as the visual order; do not use CSS reordering that confuses assistive technology.

Preserve all current permission checks, save/comment mutations, confirmation dialogs, query invalidation, and independent failure states. If the suggested-response insertion is not supported by current behavior, keep it read-only inside Intelligence rather than inventing a new mutation.

### Services

Use one page header and a local two-view switch: `Catalog` and `Requests`, each with a count and direct keyboard access. Catalog is the default because it defines the offered services; a pending approval/fulfillment count can bring attention to Requests without placing both long sections on one page.

- **Catalog:** optional compact Active/Categories summary → search/category toolbar → catalog register with Service, Category, SLA, Approval, and Actions. Pricing remains only when populated.
- **Requests:** pending/attention summary → status/approval filters → request register with Request, Requester, Approval, Fulfillment, Owner, Updated, and contextual actions.

Keep create/edit/deactivate and approve/reject/fulfill/cancel confirmations and permissions unchanged.

### Problems

Header and `New problem` → only actionable exception chips (Investigating, Known errors, Unassigned, or no summary if none matters) → search/status/owner toolbar → Problem register ordered by impact/priority and recency → details dialog with linked tickets and narratives. Remove the four-card row when it merely restates one visible record.

### Changes

Header and `New change` → clickable Awaiting review/In progress/High risk summary → search/status/risk toolbar → Change register with Title, Status, Risk, Window, Owner, Approval state, and overflow actions → detail/approval dialog. Rollback and test plans stay prominent inside detail, not in the list.

### Assets

Header and create/import action currently allowed → actionable summary such as In repair, Retired, or Unassigned (omit empty noise) → search plus Type/Status/Owner filters → inventory register with Asset, Type, Status, Owner, Location, Vendor/model, and overflow actions. Use the current card alternative below the table breakpoint.

### Knowledge Base

Header and `New article` when permitted → view chips for Published, Draft, and Archived rather than four large metrics → search and Category toolbar → two-column article library at wide widths and one column on mobile. Cards show status/category, title, concise excerpt, updated time, and one primary Read action; Edit/Delete move into a consistent action area or overflow. Views/helpful counts stay supporting metadata rather than dashboard KPIs.

### Agents

Header and permitted account action → compact role/coverage summary only when it helps staffing → search plus Role/Active filters → Active roster. Each row/card shows identity, role, title, tier/impact, and overflow actions. Existing admin authorization remains the source of truth; grouping the navigation must not expose this page or its actions to a new role.

### Surveys

Header and `Send survey` → compact CSAT/response summary → Delivery ledger as primary work content → rating distribution and trend as supporting analysis after the ledger. Empty state leads to Send survey; partial stats must not hide a usable ledger.

### Leaderboard

Header → compact current-leader highlight → Team standings as the dominant ranked list. Preserve the current scoring, tier, momentum, and resolved measures. Keep this within People navigation; do not allow gamification components to displace operational content on Dashboard or Tickets.

### My Time

Header and `Log time` → compact current-period totals → ticket filter and date scope next to the Recorded entries register → entry list/card view. Keep the ticket association, duration validation, loading/error/empty states, and dialog flow unchanged.

### Reports

Header → partial-data warning → one four-item KPI strip (Total, Open, Resolved, SLA breached) → one compact secondary-stat row only if it adds distinct measures → Ticket volume as the primary chart → Category and Status side by side → SLA compliance → resolution-time breakdown. Use readable date labels and give every chart an accessible textual summary/table alternative. Place a data warning inside an affected chart when the failure is local; use the global warning only when multiple sections are incomplete.

### Intelligence

Header and human-decision disclaimer → authorization/data-quality state → Proactive alerts → Backlog priority and SLA exposure → recommended action/evidence → Trends, Health, Workload, and Systemic issues. Order panels by urgency, not by equal grid symmetry. Keep sampling notices local to the panel they qualify and retain the existing role gate and advisory-only behavior.

### Settings

Keep the demo-locked view compact as it is. For an authenticated administrator, add local section navigation and group the current sections without changing the update API:

1. Workspace: Organization and Notifications.
2. Ticket operations: Ticketing Mode, SLA Targets, Categories, Statuses, and Priorities.
3. Integrations: Freshservice/Jira configuration and Agent Accounts.
4. AI: LLM Configuration and AI Automation.
5. Access: Security & Authentication and User & IAM.
6. System: Maintenance and System Information.

On desktop, use a sticky local index beside one scrollable content column; on mobile, use an accessible section select/jump menu. Show a sticky `Save changes`/`Discard` bar only while the form is dirty. Keep deployment-managed fields read-only, validation inline, secrets masked, destructive maintenance actions confirmed, and mutation errors in context. Section navigation changes placement only; it must not imply separate backend saves.

## 5. Responsive and interaction rules

| Width | Required arrangement |
| --- | --- |
| `>=1280px` | Fixed sidebar; wide register tables; ticket activity/properties split; dashboard queue/recommendation split. |
| `1024–1279px` | Fixed sidebar; single-column ticket detail; wrapping toolbars; tables only when their minimum width remains usable. |
| `768–1023px` | Drawer and sticky top bar; single-column pages; toolbar wraps by priority; secondary filters use drawer/popover. |
| `<768px` | Drawer; one-column cards for dense registers; full-width search; primary action first; explicit disclosures for secondary properties and filters. |

Verify at 375, 768, 1024, 1280, and 1440 pixels; include 320 pixels if it remains a supported viewport. Use at least 44-by-44-pixel touch targets for new controls. Never make a required action hover-only, icon-only without an accessible name, or dependent on color. Drawers, dialogs, disclosures, tabs, and menus must support Escape, focus containment where appropriate, trigger-focus restoration, visible focus, semantic expanded/selected state, and reduced motion.

## 6. State and compatibility contract

Every shared surface must render these states without losing its controls or context:

- initial/loading;
- complete data;
- empty data;
- filtered no-match;
- request error with retry;
- partial/sampled/stale data;
- unauthorized/forbidden;
- demo-restricted action;
- mutation pending/success/failure; and
- destructive confirmation/cancel.

Navigation grouping is presentational only. Direct routes, server checks, client permission checks, safe external URLs, React Query keys/invalidation, realtime validation, and API payloads remain unchanged. Reorganization must never reveal a protected destination, protected data, or an action that the current role cannot perform.

## 7. Delivery plan

### Phase 0 — baseline and contract

- Inventory each route against the five page families.
- Capture current screenshots and keyboard flows at the target widths.
- Record the route/role/demo matrix and state matrix before changing layout.
- Agree centrally on title, spacing, toolbar, and register tokens.

Stop if current access behavior or a critical workflow cannot be characterized. No user-facing layout ships in this phase.

### Phase 1 — shell and shared primitives

- Convert the sidebar item array into grouped metadata without changing paths or gates.
- Add PageFrame, PageHeader, ContextAlertRegion, SummaryStrip, SectionHeader, DataToolbar, and RegisterSurface as backwards-compatible compositions of current UI pieces.
- Migrate one low-risk register page as the reference implementation.

Verify every nav link and active state for each role/demo context, keyboard drawer behavior, short-height scrolling, primitive unit/component tests, and visual snapshots. Stop if a route becomes undiscoverable, a focus trap fails, or a role gate changes.

### Phase 2 — primary operations

- Migrate Dashboard, Ticket Queue, and Ticket Detail.
- Keep data hooks and mutations intact; change presentation and grouping only.
- Remove repeated display values only after proving the same fact remains visible in its higher-priority location.

Verify ticket create/open/edit/assign/status/comment flows, filter URL/back behavior, AI/advisory failure paths, audit access, partial data, all target widths, keyboard order, screen-reader landmarks, and screenshot diffs. Stop if the primary ticket task loses a required control or becomes slower in a moderated smoke test.

### Phase 3 — registers and libraries

- Migrate Services, Problems, Changes, Assets, Knowledge Base, Agents, Surveys, Leaderboard, and My Time.
- Use the shared family primitives and remove route-local duplicate layout rules only after each route passes.

Verify existing create/edit/delete/approve/fulfill/link/log-time flows, responsive card/table parity, permission checks, confirmation behavior, and every state in the compatibility contract.

### Phase 4 — analytics and administration

- Migrate Reports, Intelligence, and the authenticated Settings form.
- Finish local partial-data placement, accessible chart summaries, Settings navigation, and dirty-state behavior.

Verify protected Intelligence, masked/deployment-managed Settings fields, save/discard/unsaved navigation, maintenance confirmations, chart keyboard/screen-reader alternatives, and rollback behavior.

### Phase 5 — consolidation

- Remove only superseded route-local layout code.
- Run the complete frontend test, type-check, accessibility, visual-regression, and route smoke suites.
- Document the page-family and state contracts beside the shared components.

## 8. Verification, completion, and rollback

The migration is complete only when:

- every current authenticated route maps to a named page family and remains reachable by the same authorized users;
- the flat primary navigation has been replaced by the exact visible groups above;
- Dashboard shows the queue before duplicated supporting metrics;
- Ticket Queue uses one compact control surface and shows the register earlier than the baseline;
- Ticket Detail follows the specified wide and narrow task order;
- no summary metric remains solely to fill a grid slot;
- all state-matrix paths still render actionable feedback;
- no required control is lost at any tested width;
- keyboard navigation, focus return, headings/landmarks, accessible names, and non-color status cues have no critical/high defects; and
- existing frontend tests, type-check, route authorization tests, and relevant end-to-end flows pass.

Use per-route screenshots at 375, 768, 1024, 1280, and 1440 pixels and test at least one authorized, one forbidden, and one demo context. For the three critical pages, run a short task test: find the next ticket, filter the queue, assign/update a ticket, and post a reply. Record time, errors, and control-discovery failures; do not claim productivity gains without later production evidence.

Ship the shared primitives backwards-compatibly and migrate routes in isolated pull requests or commits. There is no database or API migration. If a route misses a stop condition, revert that route’s layout commit while retaining stable primitives; if a primitive causes cross-route regression, revert its adoption and leave route-local UI intact. Do not bundle all phases into one release.

## 9. Option ledger

| Family | Decision | Rationale |
| --- | --- | --- |
| N1 flat reorder | Reject | Does not solve scanning cost or future growth. |
| N2 visible domain groups | Select | Improves scanning while every route stays directly visible. |
| N3 collapsible groups | Defer | Hides destinations and adds state/focus complexity without height evidence. |
| N4 personalized navigation | Reject | Placement would be unstable and no usage evidence supports it. |
| P1 tokens only | Reject | Visual consistency alone leaves section hierarchy and duplication unchanged. |
| P2 canonical anatomy plus page families | Select | Creates consistency without forcing unrelated pages into one template. |
| P3 rigid four-metric template | Reject | Produces decorative zeroes and repeated counts. |
| D1 everything visible | Reject | Gives filters and secondary metadata excessive vertical weight. |
| D2 aggressive hiding | Reject | Harms discoverability and expert speed. |
| D3 progressive disclosure | Select | Keeps common work visible and moves only infrequent controls. |
| T1 vertical ticket stack | Reject | Preserves long travel and equal weighting of Activity, Audit, and AI. |
| T2 activity plus properties rail | Select at `xl` | Keeps context and frequent edits visible without fragmenting the record. |
| T3 full tabbed ticket page | Reject | Hides too much essential context and complicates deep linking/state. |
| R1 app-wide rewrite | Reject | Broad regression and rollback surface. |
| R2 cosmetic route edits | Reject | Recreates drift and inconsistent intermediate patterns. |
| R3 primitives then task-critical migration | Select | Reversible, testable, and compatible with current architecture. |

## 10. Retained unknowns and exclusions

Retain for product research: dominant production roles and tasks, compact versus comfortable density, whether My Time should remain globally visible, whether saved filters/favorites/command access later earn their complexity, actual mobile share and minimum viewport, and the durable top-level title type preference. None blocks this plan because the first implementation is presentational and reversible.

Out of scope: implementation in this task, backend/API/data-model changes, new routes or capabilities, public login/portal redesign, mockups, rebranding, permission redesign, and claims based on unavailable analytics.
