# Canonical brief: Tickety UI organization plan

## Destination and output

Produce an implementation-ready plan to better organize Tickety's current authenticated web UI, including global navigation, page anatomy, section ordering, and the arrangement of items inside the most important sections. The artifact must be concise enough to execute in phases while specific enough that a product designer and frontend engineer can make the same layout decisions without inventing missing structure.

Use direct-consensus mode. The requested output is a Markdown plan, not code or a visual mockup.

## Product context

Tickety is an IT service-management application. The authenticated Next.js UI has these current routes or capabilities: Dashboard, Tickets, ticket detail, Agents, Services, Problems, Changes, Assets, Knowledge Base, Surveys, Reports, Leaderboard, Intelligence, My Time, Profile, and Settings. Access to administration and protected intelligence is role-gated. Demo mode changes some capabilities but uses the same primary shell.

The user asked for a plan to better organize the current UI and the arrangement of all elements within sections. They did not authorize implementation in this task.

## Observed evidence

Source quality: direct inspection of repository screenshots at 1440 by 900 pixels and current React/Tailwind source. No product analytics, user interviews, or production telemetry were supplied.

- The desktop shell uses a fixed 256-pixel dark sidebar and a main content container capped at 1440 pixels. Mobile uses a drawer and sticky 64-pixel top bar.
- The sidebar presents 12 primary destinations in one flat group labeled Workspace, followed by Profile and Settings. My Time exists but is not in the primary navigation. Role gates hide Agents, Intelligence, or Settings when appropriate.
- Page headers are inconsistent. Some top-level route titles use a serif display face and others use sans serif; eyebrow placement, icon use, borders, action alignment, content width, and vertical gaps also vary.
- Dashboard order is header, warnings, a large dark Operational Pulse, four metric cards, then the priority queue and a recommendation panel. Pulse values overlap with the metric cards, creating repeated information before the primary work queue.
- Ticket Queue order is header/actions, a separate Saved Views strip, a large filter card with search, status chips, four dropdowns and sort, then the table. This gives filtering more vertical weight than the work items.
- Ticket detail order is breadcrumb, large summary card, a full-width Agent Workbench with five fields plus Conversation and Audit in equal columns, then multiple vertically stacked AI and recognition sections. Frequently changed properties, the conversation, secondary audit history, and optional AI guidance compete in one long page.
- Services, Problems, Changes, Assets, and Knowledge generally use header, four summary cards, search/filter controls, and a register or card grid, but each implements the pattern separately. Several summary cards repeat counts already visible below or show low-value zeroes.
- Reports uses a warning, two rows of KPIs, then charts. Intelligence uses a sequence of panels. Settings can become a very long configuration form in an authenticated administration context.
- Existing code already has reusable Button, Badge, Alert, Dialog, EmptyState, ErrorState, Skeleton, searchable-select, table/card responsive patterns, and design tokens. A plan should reuse and consolidate these instead of proposing an unrelated design system.
- Current screenshots have strong qualities worth preserving: clear brand contrast, readable labels, generous whitespace, visible primary actions, role-aware navigation, responsive card alternatives for several tables, and explicit loading/error/empty states.

## Constraints and assumptions

- Preserve all current capabilities, routes, role/access checks, demo restrictions, safe external-link handling, query/error behavior, and API contracts.
- Reorganization may introduce shared layout primitives and move existing UI, but it must not depend on backend changes.
- Preserve the brand palette and general visual character. This is an information-architecture and hierarchy plan, not a rebrand.
- Avoid adding speculative product features. A navigation search or command palette may be retained only as a later optional enhancement, not a prerequisite.
- Prefer task frequency and decision urgency over visual symmetry. Do not require every page to have the same number of cards.
- Desktop, tablet, and mobile arrangements must be explicit. Keyboard and screen-reader behavior must remain first-class.
- Separate observed facts from judgments and retained unknowns.
- The plan should address global patterns plus concrete arrangements for Dashboard, Ticket Queue, Ticket Detail, operational registers, people/engagement pages, Reports/Intelligence, and Settings.
- Use reversible phases and identify verification and rollback boundaries.

## Acceptance criteria

The proposed plan must:

1. Define a clear navigation grouping and exact route placement, including My Time, Profile, Settings, and role-gated items.
2. Define one canonical page sequence and shared primitives, with justified exceptions rather than forcing all pages into identical templates.
3. Give a concrete top-to-bottom arrangement for Dashboard, Ticket Queue, and Ticket Detail.
4. Give specific pattern guidance for Services, Problems, Changes, Assets, Knowledge Base, Agents, Surveys, Leaderboard, Reports, Intelligence, and Settings.
5. Reduce duplicated or low-value information and make the primary task or primary content visible earlier.
6. Specify responsive transformations at practical breakpoints without creating inaccessible hidden functionality.
7. Preserve authorization, loading, error, empty, destructive-confirmation, and partial-data behavior.
8. Define shared frontend primitives to reuse existing UI components and prevent route-by-route drift.
9. Include a phased implementation order, proportionate tests, measurable stop conditions, and a safe rollback approach.
10. Include an option ledger showing which major alternatives were selected, combined, deferred, or rejected and why.
11. Retain unknowns that require user research or product authority without making them blockers for a reversible first phase.

## Material option families

### Navigation

- N1: Keep one flat sidebar and only reorder items. Lowest implementation risk and highest immediate discoverability, but it does not solve scanning cost as the product grows.
- N2: Group the sidebar by work domain with visible group labels while keeping destination links directly accessible. Moderate change, improves scanning, and can preserve current routing and active states.
- N3: Use collapsible or nested navigation groups. Saves height and supports growth, but hides destinations and adds state and accessibility complexity.
- N4: Personalize navigation by role or recent use. Potentially efficient but unstable across users and unsupported by supplied usage evidence.
- Relevant hybrid: N2 as the baseline, retain existing role gates, keep account/admin utilities at the bottom, and defer search/command access until usage evidence supports it.

### Page structure

- P1: Standardize only visual tokens and leave each route's section order bespoke. Low risk but leaves information hierarchy inconsistent.
- P2: Introduce a canonical page anatomy: header, contextual alert, optional actionable summary, primary toolbar/content, then secondary insight or help. Strong consistency while allowing declared exceptions.
- P3: Enforce one rigid template with four metrics and one table/grid on all routes. Easy to document but produces decorative or redundant sections.
- Relevant hybrid: P2 with a small family of page types: overview, register/library, record detail, analytics, and settings.

### Density and disclosure

- D1: Keep all controls and metadata visible. High discoverability but excessive vertical weight and weak prioritization.
- D2: Aggressively hide secondary controls in menus, drawers, and tabs. Compact but can harm discovery and expert speed.
- D3: Progressive disclosure: keep the common task path visible, move infrequent filters and row actions behind labeled controls, and reveal contextual panels when needed.

### Ticket detail

- T1: Retain a single full-width vertical stack and only change spacing. Lowest risk but preserves long travel and equal weighting of primary and secondary content.
- T2: Use a two-column workbench on wide screens: main activity/conversation on the left and a sticky properties/action rail on the right, with Intelligence and Audit as explicit secondary views.
- T3: Move all record work into a multi-tab full-page interface. Compact but fragments context and can hide essential status or customer information.
- Relevant hybrid: T2, with status and primary actions always visible, Conversation as the default activity, Intelligence and Audit as labeled secondary panels, and a single-column disclosure order on smaller screens.

### Rollout

- R1: One app-wide rewrite. Produces consistency quickly but has broad regression and rollback risk.
- R2: Route-by-route cosmetic edits. Easy to ship but likely to create another inconsistent intermediate system.
- R3: Establish shared shell/page primitives, then migrate by task criticality: navigation and primitives; Dashboard/Tickets/detail; operational registers; people/analytics/settings; final responsive/accessibility polish.

## Required proposal and review checklist

Each voting seat must evaluate acceptance requirements, the listed options and relevant hybrids, necessary implementation detail, compatibility with existing behavior, failure paths, rollback, stop conditions, retained unknowns, scope exclusions, risks, and adversarial checks. A proposal must include an option ledger and a complete candidate-plan outline rather than generic design advice.

## Out of scope

- Implementing code, changing APIs or data models, creating mockups, rebranding, changing product permissions, or redesigning the public login/portal experience.
- Proving the best grouping through production analytics or user research; those inputs are not available.
- Adding new routes or backend capabilities.

## Retained unknowns

- Which roles and workflows dominate real production usage.
- Whether users prefer a compact or comfortable density.
- Whether My Time should be globally visible or only contextual from tickets/profile.
- Whether a command palette, favorites, or remembered filters would justify their complexity.
- Exact mobile usage share and minimum supported viewport.
- Product-owner preference for serif versus sans-serif top-level titles; the plan may define a consistent rule without treating the typeface choice as irreversible.
