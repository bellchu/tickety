# Destination

Decide and specify a scalable product solution for a multi-cloud architecture editor that models many provider resources even though a large portion should not appear as first-class objects on an ordinary architecture diagram. Deliver a concise but implementation-ready design contract, not code.

# Requested output

The agreed artifact must contain:

- a one-sentence product decision;
- a conceptual model separating the authoritative resource model from diagram projections;
- an explicit resource-presentation taxonomy and deterministic classification decision tree;
- default diagram intent, optional views/layers, and rules for context-dependent visibility;
- catalog/palette, resource inventory, canvas, outline, inspector, search, add/create, attach/configure, and explicit-pin behavior;
- a provider-neutral metadata/registry contract sufficient to drive the UI without hard-coding every resource into view components;
- treatment of known, unknown, unsupported, imported, child, ephemeral, attachment, selector-based, inherited, and operational resources;
- representative Azure, AWS, GCP, Microsoft 365, and Generic/Kubernetes examples;
- validation, accessibility, compatibility, migration, failure paths, rollback, stop conditions, testing/metrics, retained unknowns, scope exclusions, risks, and adversarial checks;
- a small textual product wireframe;
- a complete Mermaid development-flow graph that can track implementation progress, including dependency-ordered work packages, explicit gates/exit evidence, and stable progress states (`pending`, `in progress`, `blocked`, `complete`);
- a compact work-package ledger keyed exactly to the graph node IDs so the graph can later map to issues without requiring a specific issue tracker;
- an option ledger explaining why each material option is retained or pruned.

# Observed facts and supplied evidence

## Current editor screenshot

- The editor has a provider catalog on the left, free-form canvas in the center, and inspector on the right.
- Catalog copy says `Click to add · drag to position`, implying one placement behavior for every listed resource type.
- Azure Linux VM and Azure NSG are rendered as similarly sized peer cards with generic handles.
- The catalog reports hundreds of additional resources per provider, so a node-per-resource assumption does not scale.

The screenshot is direct evidence of current presentation but does not reveal the underlying data model.

## User statements

- Resources such as NSGs should not be presented as peer architecture nodes.
- Other cloud and SaaS platforms contain analogous attached/scoped policy resources.
- Many valid resources normally do not appear on architecture diagrams at all.

These statements establish that existence in the modeled inventory must not imply default canvas placement.

## Prior unanimously approved decision

The preceding direct debate approved this narrower NSG treatment:

- one shared NSG resource remains in a policy library/inspector;
- its valid Subnet or NIC associations appear as typed target badges;
- generic ports and permanent NSG peer cards are removed;
- a focused Security layer can reveal non-routing association relationships;
- no visual VM endpoint is silently treated as a NIC.

The broader solution should preserve that domain-accurate behavior or explicitly explain any necessary refinement.

## Cross-platform domain evidence

Official provider documentation supports several distinct non-node semantics:

- Azure NSGs associate to Subnets or NICs; route tables associate to Subnets; WAF policies associate at gateway/listener/path scope; Azure Policy and RBAC operate at resource hierarchy scopes.
- AWS Security Groups associate with network interfaces; Network ACLs associate with Subnets; WAF Web ACLs associate with protected resources; IAM managed policies attach to identities.
- GCP network firewall policies associate with VPC networks; traditional firewall rules apply at network scope and select instances via targets such as service accounts/tags; hierarchical firewall and organization policies inherit through hierarchy; Cloud Armor policies attach to backend services.
- Microsoft 365 Conditional Access, Intune, Teams, DLP, and retention policies apply through users, groups, apps, devices, locations, sites, or containers rather than physical topology placement.
- Kubernetes NetworkPolicy selects Pods within a namespace; multiple policies can select the same Pods.

These are examples, not an exhaustive catalog or proof that like-named resources have identical semantics.

## Repository check

The current workspace contains no matching multi-cloud canvas implementation under obvious provider/resource names. Do not invent code-level constraints. Specify a product and data contract to map to the actual editor later.

# Constraints and assumptions

- Every modeled resource must remain discoverable, selectable, inspectable, searchable, editable as authorized, and exportable even when absent from a diagram.
- The default architecture diagram must optimize comprehension rather than inventory completeness.
- Diagram representation is a projection/reference to an authoritative resource record, never a duplicate resource or second source of truth.
- A single universal hidden/visible Boolean is insufficient because relevance depends on diagram intent and relationship semantics.
- Do not force provider-specific concepts into a false universal equivalence. Use provider adapters/registry metadata for exact semantics.
- Prevent arbitrary links and placement when semantics are unknown; do not guess from names or icons.
- Preserve progressive disclosure, reversible actions, saved-diagram stability, multi-cloud consistency, and accessibility.
- Support explicit user documentation needs without allowing a pinned configuration record to masquerade as a runtime topology participant.
- Avoid requiring manual classification of every resource instance; classification belongs primarily to versioned resource-type metadata with narrowly scoped instance overrides.
- No product code or live provider mutation is authorized in this debate.
- The development graph is a planning and progress-tracking contract, not authorization to create issues, assign people, estimate dates, or implement work.

# Acceptance criteria

1. The default diagram excludes low-value administrative/detail resources while retaining all resources in an authoritative, accessible inventory.
2. A deterministic taxonomy distinguishes topology nodes, containers/scopes, attachments, selector/scoped policies, inherited policies, relationships, child configuration, operational artifacts, metadata, and unknowns.
3. Visibility can change by diagram purpose without changing resource truth or silently duplicating resources.
4. Creation and interaction verbs match semantics: place, contain, attach, assign, configure, inspect, or pin—not universal click-to-add/drag-to-position.
5. The contract handles provider-specific target types, cardinality, scope, inheritance, selectors, effective-state resolution, and invalid relationships.
6. A user can find and inspect any hidden resource from search, inventory, outline/layer summaries, or a target’s effective/configuration inspector.
7. Explicit pinning is supported for documentation while remaining visually and semantically distinct from topology and prohibited from gaining invented ports/relationships.
8. Unknown/unsupported/imported types fail honestly without being silently shown as ordinary nodes or disappearing completely.
9. Existing diagrams and saved layout data migrate without resource loss, connection guessing, or irreversible provider changes, and rollback is defined.
10. Keyboard, screen-reader, color-independent, zoom, density, focus, and non-drag alternatives are specified.
11. The solution is maintainable across thousands of resource types through testable registry metadata, fallbacks, governance, and provider adapters.
12. Product/design/engineering can prototype and evaluate the model without inventing its primary information architecture or state transitions.
13. The output includes valid, complete Mermaid source for a dependency graph whose stable node IDs match a work-package ledger; each package has scope, dependencies, exit evidence, and a progress state, and the flow contains rollout and rollback gates.

# Material options in scope

## Option A — Continue placing every resource as a node

- Feasibility: already implied by the current UI and simplest rendering architecture.
- Benefits: uniform behavior; nothing is hidden.
- Costs/risks: diagram becomes inventory dump; false topology; invalid ports; unusable density; child and policy resources appear autonomous.
- Retain/prune question: likely a baseline to reject, but assess whether a full-inventory view should preserve it in controlled form.

## Option B — Provider-curated allowlist of diagram-visible types

- Feasibility: high for a small catalog, increasingly costly at thousands of types.
- Benefits: excellent defaults when curated by domain experts; simple runtime check.
- Costs/risks: constant maintenance; novel/third-party resources lag; one global answer ignores diagram purpose.
- Retain/prune question: consider allowlists as generated/registry metadata rather than the entire architecture.

## Option C — Universal semantic taxonomy with automatic presentation

- Feasibility: medium-high if every resource type has validated metadata.
- Benefits: consistent cross-provider logic; scalable renderers; testability.
- Costs/risks: classifications can be wrong; semantics differ by provider; context-sensitive visibility still needs a projection model.
- Retain/prune question: evaluate as the core contract combined with provider-specific adapters and fallbacks.

## Option D — Diagram-purpose presets/layers only

- Feasibility: medium.
- Benefits: acknowledges that runtime, network, security, governance, operations, and other diagrams need different evidence.
- Costs/risks: without an independent resource model/taxonomy, presets become hard-coded filters and can hide resources unpredictably.
- Retain/prune question: evaluate as a projection mechanism, not necessarily the sole solution.

## Option E — Separate resource inventory from architecture canvas

- Feasibility: medium; requires an inventory/explorer surface in addition to the diagram palette.
- Benefits: preserves completeness without canvas clutter; makes hidden resources first-class in the product.
- Costs/risks: two surfaces increase navigation cost and may create duplicate sources of truth if implemented poorly.
- Retain/prune question: determine whether a shared resource identity plus locate/effective links resolves fragmentation.

## Option F — User-controlled visibility/pinning as the primary rule

- Feasibility: high.
- Benefits: flexible and easy to explain.
- Costs/risks: pushes domain modeling onto users; inconsistent diagrams; imported/default diagrams remain poor; pins can imply topology.
- Retain/prune question: consider only as an explicit documentation override within safe visual/semantic constraints.

## Option G — Hybrid resource registry plus intent-based diagram projections

- One authoritative inventory; versioned provider-neutral presentation roles with provider-specific semantics; a diagram stores references/projection overrides; intent presets resolve default representations; safe explicit pins; specialized renderers for nodes, boundaries, badges, overlays, relationships, inspector-only detail, and inventory-only artifacts.
- Feasibility: medium.
- Benefits: combines correctness, scalability, context, discoverability, and user control.
- Costs/risks: richer model, migration effort, governance burden, and potential surprise when changing views.
- Retain/prune question: select only if resolution order, fallbacks, catalog behavior, persistence boundary, and testing are concrete.

# Required adversarial scenarios

Each seat must mentally test at least:

- a simple VM and database runtime diagram;
- one VM with disks, NICs, IP configurations, NSG, backup, diagnostics, tags, locks, IAM/RBAC, alerts, and snapshots;
- an NSG/Security Group reused by many targets;
- a GCP firewall rule applying through tags or service accounts;
- hierarchical policy inherited from a parent scope;
- a Microsoft 365 policy targeting thousands of users/groups/apps;
- Kubernetes NetworkPolicy selecting changing Pods;
- a centralized logging or security service that is operational in one view but a meaningful data-flow node in another;
- an unknown newly released provider type;
- a third-party/custom resource;
- an imported diagram with every resource represented as a card;
- an explicit user request to document an otherwise hidden certificate, secret, tag, or role assignment;
- switching diagram intent with unsaved layout changes;
- offline/provider-unverified state;
- low zoom, dense diagrams, keyboard-only use, screen readers, and color-vision deficiency.

# Required checks for each voting seat

- Cover every acceptance criterion.
- Compare every material option and relevant hybrids.
- Specify necessary product/data-contract detail without inventing unavailable code facts.
- Address compatibility, migration, failure paths, rollback, stop conditions, testing/metrics, retained unknowns, scope exclusions, risks, and adversarial checks.
- Distinguish resource-type defaults from instance state, diagram references, effective derived state, and user documentation overrides.
- Identify where human/provider confirmation remains necessary.
- Verify that the Mermaid development-flow graph is syntactically complete, uses stable work-package IDs, expresses real dependencies and decision gates, and matches the accompanying progress ledger exactly.

# Out of scope

- Writing or modifying application code.
- Exhaustively classifying every Azure, AWS, GCP, Microsoft 365, Generic, Kubernetes, or third-party type.
- Designing full editors for policy rules, IAM, monitoring, costs, or compliance.
- Choosing final icons, colors, typography, spacing, or design-system tokens.
- Defining provider APIs, permissions, or deployment workflows beyond the UI/data contract needed for this decision.
- Treating the full resource inventory as a conventional architecture diagram.

# Decision rule

Prefer the smallest coherent model that keeps the default diagram truthful and readable, keeps the inventory complete and navigable, adapts to diagram intent, prevents invented topology, scales through versioned metadata rather than ad hoc UI exceptions, and fails honestly for unknown semantics.
