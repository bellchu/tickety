# Destination

Decide and specify a better product/UI representation for policy-like cloud resources such as an Azure Network Security Group (NSG) in a multi-cloud infrastructure design canvas. Deliver a concise, implementation-ready design recommendation, not code.

# Requested output

The agreed artifact must contain:

- a one-sentence decision;
- the conceptual model and visual hierarchy;
- add, attach, select, inspect, edit, detach, reuse, and delete interactions;
- treatment of subnet-level versus NIC-level NSG association;
- canvas, catalog, inspector, validation, and accessibility behavior;
- a small textual wireframe or complete Mermaid diagram;
- compatibility and migration guidance from the current peer-node representation;
- failure paths, rollback, stop conditions, retained unknowns, scope exclusions, risks, and adversarial checks;
- an option ledger explaining why each material option is retained or pruned.

# Observed facts and evidence

## User-supplied screenshot

- The editor has a catalog on the left, a free-form canvas in the center, and an inspector on the right.
- Azure `Linux VM` and Azure `NSG` are both represented as similarly sized, independent rectangular resource cards on the canvas.
- Both cards expose generic circular connection handles on all four sides.
- The NSG card is named `allow-web`, carries `Azure · NSG` and a `Regional` chip, and floats below the VM as a peer object.
- The editor is in Connect mode and reports a `Needs verification` state.
- The user explicitly says resources like NSG should not be presented this way and asks for a better solution.

The screenshot is direct evidence of the current presentation, but it does not reveal the underlying data model or implementation.

## Domain evidence

- Microsoft documents an NSG as a set of inbound and outbound security rules that filters virtual-network traffic.
- An NSG associates to a subnet or to a network interface (NIC), not directly to a VM as a generic topology link. One NSG can be reused by multiple subnets and NICs.
- A VM can be affected by both a subnet-associated NSG and a NIC-associated NSG; effective rules are aggregated, and traffic must pass both relevant layers.
- Primary sources:
  - https://learn.microsoft.com/en-us/azure/virtual-network/network-security-group-how-it-works
  - https://learn.microsoft.com/en-us/azure/virtual-network/manage-network-security-group
  - https://learn.microsoft.com/en-us/azure/network-watcher/effective-security-rules-overview

## Repository check

The current workspace contains no matching NSG/resource-canvas implementation by obvious resource names, so this decision must not invent code-level constraints. It should define a design contract that can be mapped to the actual editor later.

# Constraints and assumptions

- Preserve NSGs as real, independently named, reusable, selectable, inspectable, and deletable resources.
- Do not visually imply that an NSG forwards traffic, has arbitrary directional ports, or connects directly to any resource type.
- Keep the canvas readable at both small and larger topology sizes.
- Make security scope and inheritance legible without forcing all rule details onto the canvas.
- Support both novice comprehension and expert access to exact association targets and effective-rule detail.
- Prevent invalid associations rather than merely warning after a generic connection.
- Keep the recommendation extensible to other policy-like resources only where their semantics truly match; do not flatten unlike concepts into one universal decoration.
- Prefer progressive disclosure and semantic ports/actions over generic graph handles.
- No implementation or external product mutation is authorized in this debate.

# Acceptance criteria

1. A viewer can distinguish deployable topology entities, containment scopes, connections, and attached policies at a glance.
2. The representation accurately distinguishes subnet association from NIC association and never silently equates NIC with VM.
3. Reused NSGs remain discoverable and editable as one shared resource; the UI reveals all associations and the blast radius of edits/deletion.
4. Users can add and associate an NSG with fewer opportunities for invalid connections than the current generic peer node.
5. The default canvas stays compact, while rule summaries, provenance, conflicts, and effective security are available on demand.
6. Keyboard, screen-reader, color-independent, focus, and target-size behavior is specified.
7. The design supports migration of existing saved diagrams without data loss and offers a rollback path.
8. Validation states distinguish incomplete configuration, invalid association, conflicting/effective policy concerns, and unknown/provider-unverified state.
9. The recommendation covers empty, single-use, reused, detached, inherited, overlapping subnet-plus-NIC, deleted, and unresolved-target cases.
10. The output is specific enough for product, design, and engineering to prototype without inventing the primary interaction model.

# Material options in scope

## Option A — Keep NSG as a peer node, improve its shape and typed handles

- Feasibility: high; smallest change to a node-and-edge canvas.
- Benefits: preserves uniform selection, layout, reuse, and existing graph persistence.
- Costs/risks: still overstates NSG as a topology peer and consumes canvas space; connecting lines can resemble traffic paths.
- Retain/prune question: retain only if typed association semantics and reuse visibility outweigh the conceptual mismatch.

## Option B — Attached policy badge/chip on the association target

- Feasibility: high if target resources expose attachment slots.
- Benefits: compact and semantically reads as configuration applied to a target.
- Costs/risks: one shared NSG appears in multiple places; identity, reuse, selection, and update blast radius can become unclear.
- Retain/prune question: evaluate whether a shared-resource affordance and central inspector/library can resolve the duplication problem.

## Option C — Security boundary/overlay around the protected scope

- Feasibility: medium; fits subnet scope and visually communicates coverage.
- Benefits: strong scope-at-a-glance for subnet associations.
- Costs/risks: poor fit for NIC-level association, overlap/nesting can become noisy, and geometry may imply stronger isolation than the rules provide.
- Retain/prune question: consider as a selective visualization, not necessarily the primary resource representation.

## Option D — Association edge or edge annotation between NSG and subnet/NIC

- Feasibility: high in a graph model.
- Benefits: keeps the NSG as one shared resource and shows exact targets.
- Costs/risks: lines can be mistaken for traffic flow and become spaghetti under reuse.
- Retain/prune question: consider a distinct non-routing line style or show-on-demand relationship view.

## Option E — Separate policy rail/layer/library off the topology canvas

- Feasibility: medium; requires a second spatial or list-based view.
- Benefits: clean topology and strong shared-policy identity and management.
- Costs/risks: security becomes out of sight and scope is harder to understand while arranging infrastructure.
- Retain/prune question: evaluate as a management surface paired with in-canvas indicators.

## Option F — Hybrid progressive-disclosure model

- Primary canvas representation could be target-attached semantic badges; a shared resource remains in a policy library/inspector; focus or a security-layer toggle reveals non-routing association lines and optional scope overlays; expansion can temporarily materialize a full policy card.
- Feasibility: medium-high.
- Benefits: may preserve compactness, semantic accuracy, shared identity, and expert detail.
- Costs/risks: more states and interactions to teach; hidden relationships must remain discoverable and accessible.
- Retain/prune question: select only if the state model, default behavior, and reuse handling are unambiguous.

# Required checks for each voting seat

- Cover every acceptance criterion.
- Compare all option families and any relevant hybrid.
- Provide necessary product and implementation-contract detail without inventing unavailable code facts.
- Address compatibility, migration, failure paths, rollback, stop conditions, retained unknowns, scope exclusions, risks, and adversarial checks.
- Test the proposal mentally against: a single VM with one NIC; a multi-NIC VM; a subnet with many workloads; one NSG reused across multiple subnets/NICs; both subnet and NIC NSGs; an unattached NSG; an unresolved imported target; deletion of a reused NSG; zoomed-out canvas; keyboard-only use; and color-vision deficiency.

# Out of scope

- Writing or modifying application code.
- Redesigning the entire catalog, canvas, or inspector beyond what this resource treatment requires.
- Defining the contents or authoring UX of individual NSG rules in depth.
- Claiming that every policy-like resource across Azure, AWS, GCP, or Microsoft 365 has identical attachment semantics.
- Choosing a final visual style, icon set, typography, or color tokens without the product design system.

# Decision rule

Prefer the smallest coherent interaction model that is domain-accurate, keeps security visible, preserves shared-resource identity and reuse, prevents invalid associations, and remains usable under scale and accessibility constraints. Retain genuine unknowns rather than guessing missing implementation details.
