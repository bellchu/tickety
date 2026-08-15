debate-protocol: 2
debate-scope: direct
debate-version: v0

# Decision

Represent an Azure NSG as one shared policy resource in a policy library/inspector and surface each valid application as a compact, typed badge on the associated Subnet or NIC; remove NSG peer cards and generic connection handles from the default topology canvas, and reveal associations only in a focused Security view.

# Why this model

The current card says “independent topology object with arbitrary ports.” The Azure model says “reusable rule set associated with a Subnet or NIC.” The UI should therefore separate four concepts:

1. **Topology entities** — VM, NIC, gateway, and similar deployable/connectivity objects.
2. **Containment scopes** — VNet and Subnet regions.
3. **Connections** — traffic/topology relationships.
4. **Policies and attachments** — one named shared policy plus typed `applies to` associations.

An attachment badge is a view of an association, not a copy of the NSG. Effective security is derived from all applicable layers and is not a new node or edge.

# Default presentation

- Do not place an NSG as a free-floating, VM-sized card on the ordinary canvas.
- Do not give it four generic ports or let users draw an NSG-to-VM connection.
- Keep `allow-web` as one selectable resource in a **Policies** section of the existing catalog/library. Its row shows provider/type, verification state, and association count.
- On a Subnet, render a badge on the scope boundary: `shield  allow-web · Subnet`.
- On a NIC, render a badge in the NIC row/attachment slot: `shield  allow-web · NIC`.
- If NICs are normally collapsed inside a VM, the VM may show a summary such as `Security: subnet + 1 NIC policy`; selecting or attaching expands named NICs. The badge never attaches to the VM identity.
- At low zoom, collapse badges to `shield + count/status`; never shrink away all evidence that a policy is applied.
- An unattached NSG stays in Policies with an `Unattached` informational state. It does not float as a phantom topology node.

# Focused Security view

The default canvas shows badges but no association lines. A keyboard-accessible **Security** layer or `Locate all associations` action may reveal only the focused NSG’s relationships:

- use dashed, non-arrowed, labelled lines (`applies to`), without topology ports;
- show the shared policy as a temporary focus card or library anchor, not a permanently placed canvas node;
- optionally highlight a selected Subnet boundary to communicate scope;
- never use a boundary overlay for NIC association or imply that an NSG forwards traffic or guarantees isolation;
- hide lines and detailed overlays again when focus/layer mode ends.

# Interaction contract

## Add and attach

- Clicking `Azure NSG` creates a named, optionally unattached resource in Policies and opens its inspector.
- Dragging the NSG resource type or an existing NSG highlights only semantically valid Subnet and NIC drop targets. The mode label changes from generic `Connect` to `Attach NSG`.
- Dropping on a Subnet creates/uses a Subnet association. Dropping on an exposed NIC creates/uses a NIC association.
- From a collapsed or multi-NIC VM, `Attach NSG…` opens a required named-NIC chooser; it never silently selects a primary NIC.
- The reciprocal flow exists in a Subnet/NIC inspector: `Attach policy` opens a filtered NSG picker.
- Invalid resource types are disabled before drop/selection. Provider constraints such as target scope and association cardinality are enforced by the provider adapter; replacement requires explicit confirmation.

## Select and inspect

- Selecting a policy row selects the shared NSG and can highlight all of its associations.
- Selecting a badge selects that exact association while retaining a link to the shared NSG.
- The NSG inspector shows identity, concise inbound/outbound rule summary, verification/provenance, associations grouped by `Subnets` and `NICs`, locate actions, and edit/delete blast radius.
- A target’s **Security** section shows direct NIC policy, inherited Subnet policy, their provenance, and `View effective security` per concrete NIC.
- If both Subnet and NIC NSGs apply, show neutral `Multiple security layers` with both names. Claim a conflict or effective allow/deny only when provider-backed evaluation supports it.

## Edit, detach, reuse, and delete

- Rule edits affect the one shared resource. Before commit, show how many associations/targets may be affected; require extra confirmation for a reused NSG.
- Detach acts on the selected Subnet or NIC association only and leaves the NSG and other associations intact.
- Reuse is first-class: the policy row shows association count, `Attach to another target`, and `Locate all`.
- Deleting an attached/reused NSG first lists every known target and offers `Cancel`, `Replace associations` where supported, or `Detach all and delete`. Never silently remove protection.
- Failed attach/edit/detach/delete keeps the last confirmed state, identifies the affected target(s), and marks any optimistic UI as pending/error until reconciled.

# Wireframe

```text
CATALOG / POLICIES           CANVAS                                  INSPECTOR
Azure resources              VNet: prod                              allow-web · Azure NSG
…                            ┌─ Subnet: web ─────────────────────┐   Verified · 3 associations
Policies                     │ [shield allow-web · Subnet]       │   Rules: 6 inbound · 3 outbound
[+] Azure NSG                │  VM web-1                         │
allow-web        3 targets   │   ▸ NICs · 1 policy              │   Associations
db-only          Unattached  │  VM api-1                         │   Subnets: web
                             │   ▾ NIC: api-primary              │   NICs: api-primary, worker-nic
Security layer [off]         │     [shield allow-web · NIC]      │
                             └────────────────────────────────────┘   [Locate all] [Edit] [Delete]
```

# Validation states

Use icon, text, and accessible name in addition to color.

- **Unattached** — valid resource with zero associations; informational, not automatically an error.
- **Incomplete configuration** — required identity, rules, or provider fields are missing.
- **Invalid association** — missing/wrong target type, ambiguous VM endpoint, scope/cardinality mismatch, stale target, or provider rejection. Block new invalid actions.
- **Multiple security layers** — both Subnet and NIC policy apply; informational until evaluation identifies a concrete concern.
- **Effective-policy concern** — provider-backed or explicitly rule-engine-backed result needs review.
- **Unknown / provider-unverified** — import ambiguity, stale read, pending mutation, or unavailable effective-rule evaluation. Never display this as healthy or definitively conflicting.

Expose compact state on the badge and library row, and the explanation/remediation in the inspector. `Needs verification` must identify whether the uncertainty belongs to the policy, association, target, or effective result.

# Accessibility

- Badge, policy row, layer toggle, attach picker, menus, and association-list items are keyboard operable with visible focus; drag always has a menu/picker equivalent.
- Accessible badge names include policy name, association level, concrete target, verification state, and warning count.
- The inspector/list is the textual equivalent of any line or overlay, so a screen reader never depends on canvas geometry.
- State is never color-only; use text plus icon/pattern. Preserve contrast and a minimum 24×24 CSS-pixel target, expanding compact hit areas toward 44×44 where layout permits.
- Announce attach, detach, validation, and mutation outcomes through a non-interruptive live region.

# Compatibility, migration, and rollback

1. Preserve existing NSG IDs, names, rules, provider metadata, association records, and legacy layout/link metadata.
2. Convert a legacy edge only when its stored semantics prove an NSG-to-Subnet or NSG-to-NIC association.
3. Never infer that a visual edge to a VM means its primary NIC. If stored data identifies a concrete NIC, map that NIC; otherwise create an `Unresolved imported target` migration item for human selection.
4. Unresolved records do not create a healthy badge or deployable association. They appear in a Migration review surface with locate/retarget/remove actions.
5. Gate the new representation behind a schema/view version and retain a read-only legacy compatibility view until migrated diagrams are confirmed.
6. Rollback restores the prior representation from preserved metadata without changing cloud resources. Migration must not attach, detach, edit, or delete provider resources.

# Failure paths and stop conditions

- If target identity, type, NIC choice, scope compatibility, provider state, or shared-resource impact is unknown, stop the destructive/associative action and request resolution.
- If provider verification is unavailable, preserve the intended edit separately from confirmed state and label it pending/unverified; do not fabricate effective rules.
- If a reused edit fails, retain the last confirmed shared rules and report which targets remain confirmed or uncertain.
- If an imported target is gone, keep an unresolved placeholder/reference until the user explicitly retargets or removes it.
- Stop migration rather than guessing when legacy endpoint semantics are ambiguous.
- Stop this recommendation at the design contract; code changes, provider mutations, bulk deletion, and detailed rule-authoring design are not authorized.

# Option ledger

- **A — improved peer node:** prune as the primary design. Typed handles reduce invalid links but the node still looks like a traffic participant and wastes space. Retain only as a reversible legacy view.
- **B — target badge:** retain as the default in-canvas representation. It communicates “applied here” compactly. Shared identity is protected by the central policy record.
- **C — security boundary/overlay:** retain only as an on-demand Subnet visualization. It is strong for scope but wrong for NICs and can overstate isolation.
- **D — association edge:** retain only in focused Security view. A dashed, non-arrowed, labelled relationship can reveal reuse, but permanent lines create fake traffic paths and spaghetti.
- **E — separate policy library:** retain as the single home for identity, unattached resources, search, association inventory, and lifecycle management; pair it with visible canvas badges so security is not out of sight.
- **F — hybrid progressive disclosure:** select. B + E are the primary model; C + D are controlled inspection aids; A is migration-only.

# Acceptance checks

- Single VM/one NIC: attach targets the named NIC; Subnet inheritance is separately visible.
- Multi-NIC VM: chooser and inspector operate per NIC; no VM-level association is invented.
- One Subnet/many workloads: one Subnet badge communicates shared scope without per-VM duplication.
- Reused NSG: one resource identity, many badges, association inventory, locate-all, and blast-radius confirmation.
- Subnet plus NIC NSGs: both layers and provenance are shown; no unsupported precedence/conflict claim.
- Empty/detached: library-visible, editable, and explicitly `Unattached`, with no floating node.
- Unresolved import: no guessed NIC and no healthy badge.
- Reused deletion: all targets are enumerated before any detach/delete.
- Low zoom: policy presence/count remains discoverable without lines.
- Keyboard/color-vision/screen-reader use: every status, relationship, and action has a non-geometric, non-color, non-drag equivalent.

# Retained unknowns and scope exclusions

Unknown until implementation discovery: the editor’s persistence/graph APIs, whether NICs already exist as first-class entities, existing undo/audit semantics, provider mutation and verification contracts, effective-rule calculation availability, performance thresholds, and final design-system tokens. These unknowns affect implementation but do not change the primary interaction model.

Out of scope: full NSG rule authoring; redesign of unrelated catalog/canvas behavior; an assertion that all cross-cloud policies share NSG semantics; final typography/icon/color choices; and any code or live-cloud mutation.

# Risks and mitigations

- **Hidden relationships:** persistent target badges, counts, search, `Locate all`, and a Security layer.
- **Badge crowding:** count summaries, zoom rules, and expanded detail only on focus.
- **Duplicate-looking shared policy:** badges identify associations; the inspector always links to the one policy record and its total association count.
- **Overlay implies isolation:** on-demand Subnet-only highlight with an explicit “filters traffic; not an isolation boundary” legend.
- **Lines imply traffic:** non-arrowed, dashed, labelled `applies to`, focus-only, and no ports.
- **Surprising shared edits/deletes:** blast-radius inventory, confirmation, reversible editor history, and no silent detach.
