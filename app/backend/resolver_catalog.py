"""Read-only recommendations from AI resolver codes to provider groups.

The recommender deliberately treats the provider directory as a catalog, not
as a write target. Current synchronized assignment observations are provenance
checked and each ticket can vote for at most one group, so agents who belong to
several groups cannot amplify a candidate merely because their directory
membership fans out. Correlation is not treated as successful resolution.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Callable, Collection, Iterable, Optional

from sqlalchemy import and_, case, func
from sqlalchemy.orm import Session, load_only

from .ai_contracts import (
    AI_RESOLVER_TEAMS,
    ResolverRoutingAnalysis,
)
from .database import (
    AIArtifactRecord,
    DirectoryPersonExternalIdentityRecord,
    DirectoryPersonLocalAccountRecord,
    ExternalGroupMembershipRecord,
    ExternalGroupRecord,
    ExternalUserRecord,
    TicketRecord,
    UserExternalIdentityLinkRecord,
    UserRecord,
)


HISTORY_TICKET_LIMIT = 5_000
RECOMMENDATION_WINDOW_DAYS = 365
AGENT_RECOMMENDATION_WINDOW_DAYS = 30
MIN_AGENT_RECOMMENDATION_WINDOW_DAYS = 7
MAX_AGENT_RECOMMENDATION_WINDOW_DAYS = 365
CATALOG_SCOPE_LIMIT = 50
QUERY_ID_BATCH_SIZE = 400
MIN_GROUP_TICKETS = 10
MIN_DISTINCT_AGENTS = 2
MIN_TOP_SHARE = 0.60
MIN_RUNNER_UP_LEAD = 0.15
MIN_EVIDENCE_COVERAGE = 0.60
MIN_CONFIDENCE = 0.55
MIN_AGENT_HISTORY_TICKETS = 3
MIN_AGENT_TOP_SHARE = 0.60
MIN_AGENT_RUNNER_UP_LEAD = 0.20
MIN_AGENT_CONFIDENCE = 0.35
WILSON_95_Z = 1.959963984540054
AGENT_MEMBERSHIP_PLACEHOLDER_PROFILE_JSON = (
    '{"source":"agent_membership_projection"}'
)


def _normalized_scope_value(value: object) -> Optional[str]:
    normalized = str(value or "").strip()
    return normalized or None


def _scope_key(
    binding_id: object,
    provider: object,
    workspace_id: object,
) -> tuple[str, str, Optional[str]]:
    return (
        str(binding_id or "legacy").strip() or "legacy",
        str(provider or "").strip().lower(),
        _normalized_scope_value(workspace_id),
    )


def _scope_payload(
    scope: tuple[str, str, Optional[str]],
) -> dict[str, Optional[str]]:
    return {
        "binding_id": scope[0],
        "provider": scope[1],
        "workspace_id": scope[2],
    }


def _routing_payload(ticket: TicketRecord) -> Optional[dict[str, Any]]:
    """Project the same closed route bundle used by the API."""
    candidate = {
        "primary_group": ticket.ai_suggested_team,
        "secondary_group": ticket.ai_secondary_team,
        "confidence": ticket.ai_routing_confidence,
        "scope": ticket.ai_routing_scope,
        "affected_service": ticket.ai_affected_service,
        "failure_domain": ticket.ai_failure_domain,
        "reason": ticket.ai_routing_reason,
    }
    try:
        return ResolverRoutingAnalysis.model_validate(candidate).model_dump()
    except ValueError:
        return None


def _routing_content_hash(payload: dict[str, Any]) -> str:
    serialized = json.dumps(
        payload,
        sort_keys=True,
        default=str,
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def current_route_artifact_ticket_ids(
    db: Session,
    tickets: Collection[TicketRecord],
    *,
    pipeline_version: str,
    model: str,
    allow_synthetic: bool,
    input_hash_for_ticket: Optional[Callable[[TicketRecord], str]] = None,
    require_unique_active_artifact: bool = False,
) -> set[str]:
    """Return ticket IDs whose exact persisted route provenance is current."""
    tickets_by_id = {ticket.id: ticket for ticket in tickets}
    if not tickets_by_id:
        return set()

    artifacts: list[AIArtifactRecord] = []
    ticket_ids = list(tickets_by_id)
    for offset in range(0, len(ticket_ids), QUERY_ID_BATCH_SIZE):
        query = db.query(AIArtifactRecord).options(load_only(
            AIArtifactRecord.ticket_id,
            AIArtifactRecord.input_hash,
            AIArtifactRecord.pipeline_version,
            AIArtifactRecord.model,
            AIArtifactRecord.synthetic,
            AIArtifactRecord.content_hash,
        )).filter(
            AIArtifactRecord.ticket_id.in_(
                ticket_ids[offset:offset + QUERY_ID_BATCH_SIZE]
            ),
            AIArtifactRecord.artifact == "route",
            AIArtifactRecord.active.is_(True),
        )
        if not allow_synthetic:
            query = query.filter(AIArtifactRecord.synthetic.is_(False))
        artifacts.extend(query.all())

    artifact_counts = Counter(artifact.ticket_id for artifact in artifacts)
    trusted: set[str] = set()
    for artifact in artifacts:
        ticket = tickets_by_id.get(artifact.ticket_id)
        payload = _routing_payload(ticket) if ticket is not None else None
        recomputed_input_hash = (
            input_hash_for_ticket(ticket)
            if ticket is not None and input_hash_for_ticket is not None
            else ticket.ai_routing_input_hash if ticket is not None else None
        )
        if (
            ticket is not None
            and (
                not require_unique_active_artifact
                or artifact_counts[artifact.ticket_id] == 1
            )
            and payload is not None
            and artifact.pipeline_version == pipeline_version
            and artifact.model == model
            and bool(ticket.ai_routing_input_hash)
            and recomputed_input_hash == ticket.ai_routing_input_hash
            and artifact.input_hash == ticket.ai_routing_input_hash
            and artifact.content_hash == _routing_content_hash(payload)
        ):
            trusted.add(ticket.id)
    return trusted


def _history_candidates(
    db: Session,
    *,
    since: datetime,
    through: datetime,
    history_limit: int,
) -> tuple[list[TicketRecord], bool]:
    rows = db.query(TicketRecord).options(load_only(
        TicketRecord.id,
        TicketRecord.binding_id,
        TicketRecord.external_source,
        TicketRecord.external_assignee_id,
        TicketRecord.external_group_id,
        TicketRecord.external_workspace_id,
        TicketRecord.subject,
        TicketRecord.description,
        TicketRecord.reporter,
        TicketRecord.external_requester_email,
        TicketRecord.external_conversation_text,
        TicketRecord.external_category,
        TicketRecord.external_subcategory,
        TicketRecord.external_item_category,
        TicketRecord.ai_suggested_team,
        TicketRecord.ai_secondary_team,
        TicketRecord.ai_routing_confidence,
        TicketRecord.ai_routing_scope,
        TicketRecord.ai_affected_service,
        TicketRecord.ai_failure_domain,
        TicketRecord.ai_routing_reason,
        TicketRecord.ai_routing_input_hash,
        TicketRecord.external_updated_at,
    )).filter(
        TicketRecord.external_source.isnot(None),
        func.length(func.trim(TicketRecord.external_source)) > 0,
        func.length(func.trim(TicketRecord.binding_id)) > 0,
        TicketRecord.external_assignee_id.isnot(None),
        TicketRecord.external_assignee_id != "",
        TicketRecord.ai_suggested_team.in_(AI_RESOLVER_TEAMS),
        TicketRecord.ai_routing_input_hash.isnot(None),
        TicketRecord.external_updated_at.isnot(None),
        TicketRecord.external_updated_at >= since,
        TicketRecord.external_updated_at <= through,
    ).order_by(
        TicketRecord.external_updated_at.desc(),
        TicketRecord.id.asc(),
    ).limit(history_limit + 1).all()
    return rows[:history_limit], len(rows) > history_limit


def _chunks(values: list[str]) -> Iterable[list[str]]:
    for offset in range(0, len(values), QUERY_ID_BATCH_SIZE):
        yield values[offset:offset + QUERY_ID_BATCH_SIZE]


def _membership_evidence_rows(
    db: Session,
    trusted_ticket_ids: Collection[str],
) -> list[tuple[Any, ...]]:
    """Return one aggregated membership row per trusted ticket and agent."""
    results: list[tuple[Any, ...]] = []
    for ticket_ids in _chunks(list(trusted_ticket_ids)):
        direct_group = func.max(case((
            ExternalGroupRecord.external_id == TicketRecord.external_group_id,
            ExternalGroupRecord.id,
        ), else_=None))
        rows = db.query(
            TicketRecord.id,
            TicketRecord.binding_id,
            TicketRecord.external_source,
            TicketRecord.external_workspace_id,
            TicketRecord.ai_suggested_team,
            TicketRecord.external_group_id,
            ExternalUserRecord.id,
            func.count(func.distinct(ExternalGroupRecord.id)),
            func.max(ExternalGroupRecord.id),
            direct_group,
        ).join(
            ExternalUserRecord,
            and_(
                ExternalUserRecord.binding_id == TicketRecord.binding_id,
                ExternalUserRecord.provider == TicketRecord.external_source,
                ExternalUserRecord.external_id
                == TicketRecord.external_assignee_id,
            ),
        ).join(
            ExternalGroupMembershipRecord,
            ExternalGroupMembershipRecord.external_user_id
            == ExternalUserRecord.id,
        ).join(
            ExternalGroupRecord,
            and_(
                ExternalGroupRecord.id
                == ExternalGroupMembershipRecord.external_group_id,
                ExternalGroupRecord.binding_id == TicketRecord.binding_id,
                ExternalGroupRecord.provider == TicketRecord.external_source,
                func.coalesce(ExternalGroupRecord.workspace_id, "")
                == func.coalesce(TicketRecord.external_workspace_id, ""),
            ),
        ).filter(
            TicketRecord.id.in_(ticket_ids),
            ExternalUserRecord.active.is_(True),
            func.lower(ExternalUserRecord.user_type) == "agent",
            ExternalGroupMembershipRecord.membership_kind == "member",
            ExternalGroupRecord.active.is_(True),
            ExternalGroupRecord.profile_json
            != AGENT_MEMBERSHIP_PLACEHOLDER_PROFILE_JSON,
        ).group_by(
            TicketRecord.id,
            TicketRecord.binding_id,
            TicketRecord.external_source,
            TicketRecord.external_workspace_id,
            TicketRecord.ai_suggested_team,
            TicketRecord.external_group_id,
            ExternalUserRecord.id,
        ).all()
        results.extend(rows)
    return results


def _catalog_scopes(
    db: Session,
) -> tuple[list[tuple[str, str, Optional[str]]], bool]:
    rows = db.query(
        ExternalGroupRecord.binding_id,
        ExternalGroupRecord.provider,
        ExternalGroupRecord.workspace_id,
    ).filter(
        ExternalGroupRecord.active.is_(True),
        ExternalGroupRecord.profile_json
        != AGENT_MEMBERSHIP_PLACEHOLDER_PROFILE_JSON,
        func.length(func.trim(ExternalGroupRecord.binding_id)) > 0,
        func.length(func.trim(ExternalGroupRecord.provider)) > 0,
    ).group_by(
        ExternalGroupRecord.binding_id,
        ExternalGroupRecord.provider,
        ExternalGroupRecord.workspace_id,
    ).order_by(
        ExternalGroupRecord.binding_id.asc(),
        ExternalGroupRecord.provider.asc(),
        ExternalGroupRecord.workspace_id.asc(),
    ).limit(CATALOG_SCOPE_LIMIT + 1).all()
    scopes = [_scope_key(*row) for row in rows[:CATALOG_SCOPE_LIMIT]]
    return scopes, len(rows) > CATALOG_SCOPE_LIMIT


def _abstention_reason(
    *,
    trusted: int,
    eligible: int,
    matched: int,
    top_count: int,
    distinct_agents: int,
    share: float,
    lead: float,
    confidence: float,
) -> str:
    if trusted == 0:
        return "no_trusted_history"
    if matched == 0:
        return "no_unambiguous_membership_evidence"
    if matched / trusted < MIN_EVIDENCE_COVERAGE:
        return "insufficient_evidence_coverage"
    if top_count < MIN_GROUP_TICKETS:
        return "insufficient_ticket_sample"
    if distinct_agents < MIN_DISTINCT_AGENTS:
        return "insufficient_agent_diversity"
    if share < MIN_TOP_SHARE:
        return "low_dominance"
    if lead < MIN_RUNNER_UP_LEAD:
        return "ambiguous_lead"
    if confidence < MIN_CONFIDENCE:
        return "low_sample_adjusted_confidence"
    return "recommended"


def wilson_lower_bound(successes: int, total: int) -> float:
    """Return the 95% Wilson lower bound for a bounded observed proportion."""
    if total <= 0 or successes <= 0:
        return 0.0
    bounded_successes = min(successes, total)
    proportion = bounded_successes / total
    z_squared = WILSON_95_Z ** 2
    denominator = 1 + z_squared / total
    centre = proportion + z_squared / (2 * total)
    spread = WILSON_95_Z * math.sqrt(
        (proportion * (1 - proportion) + z_squared / (4 * total)) / total
    )
    return max(0.0, min(proportion, (centre - spread) / denominator))


def recommend_resolver_catalog_mappings(
    db: Session,
    *,
    pipeline_version: str,
    model: str,
    allow_synthetic: bool,
    input_hash_for_ticket: Callable[[TicketRecord], str],
    generated_at: Optional[datetime] = None,
    history_limit: int = HISTORY_TICKET_LIMIT,
) -> dict[str, Any]:
    """Build bounded, advisory-only resolver-code catalog recommendations."""
    if history_limit < 1 or history_limit > HISTORY_TICKET_LIMIT:
        raise ValueError("history_limit is outside the bounded recommendation policy")
    now = generated_at or datetime.utcnow()
    since = now - timedelta(days=RECOMMENDATION_WINDOW_DAYS)
    history, history_truncated = _history_candidates(
        db,
        since=since,
        through=now,
        history_limit=history_limit,
    )
    trusted_ids = current_route_artifact_ticket_ids(
        db,
        history,
        pipeline_version=pipeline_version,
        model=model,
        allow_synthetic=allow_synthetic,
        input_hash_for_ticket=input_hash_for_ticket,
        require_unique_active_artifact=True,
    )
    trusted_tickets = [ticket for ticket in history if ticket.id in trusted_ids]

    # These buckets contain counts and opaque internal keys only.  No agent
    # identity is ever copied to the response payload.
    scope_code_stats: dict[tuple[tuple[str, str, Optional[str]], str], dict[str, Any]] = {}
    for ticket in trusted_tickets:
        scope = _scope_key(
            ticket.binding_id,
            ticket.external_source,
            ticket.external_workspace_id,
        )
        key = (scope, ticket.ai_suggested_team)
        bucket = scope_code_stats.setdefault(key, {
            "trusted": 0,
            "eligible": 0,
            "ambiguous": 0,
            "groups": defaultdict(lambda: {
                "tickets": 0,
                "direct": 0,
                "sole_membership": 0,
                "agents": set(),
            }),
        })
        bucket["trusted"] += 1

    membership_rows = _membership_evidence_rows(db, sorted(trusted_ids))
    selected_group_ids: set[str] = set()
    for (
        _ticket_id,
        binding_id,
        provider,
        workspace_id,
        resolver_code,
        assigned_external_group_id,
        agent_record_id,
        membership_count,
        sole_group_id,
        direct_group_id,
    ) in membership_rows:
        scope = _scope_key(binding_id, provider, workspace_id)
        bucket = scope_code_stats[(scope, resolver_code)]
        bucket["eligible"] += 1
        if direct_group_id:
            selected_group_id = direct_group_id
            evidence_kind = "direct"
        elif (
            not str(assigned_external_group_id or "").strip()
            and int(membership_count or 0) == 1
            and sole_group_id
        ):
            selected_group_id = sole_group_id
            evidence_kind = "sole_membership"
        else:
            bucket["ambiguous"] += 1
            continue
        group_bucket = bucket["groups"][selected_group_id]
        group_bucket["tickets"] += 1
        group_bucket[evidence_kind] += 1
        group_bucket["agents"].add(agent_record_id)
        selected_group_ids.add(selected_group_id)

    catalog_groups = {}
    if selected_group_ids:
        for group_ids in _chunks(sorted(selected_group_ids)):
            rows = db.query(ExternalGroupRecord).options(load_only(
                ExternalGroupRecord.id,
                ExternalGroupRecord.binding_id,
                ExternalGroupRecord.provider,
                ExternalGroupRecord.external_id,
                ExternalGroupRecord.workspace_id,
                ExternalGroupRecord.name,
                ExternalGroupRecord.active,
            )).filter(
                ExternalGroupRecord.id.in_(group_ids),
                ExternalGroupRecord.active.is_(True),
                ExternalGroupRecord.profile_json
                != AGENT_MEMBERSHIP_PLACEHOLDER_PROFILE_JSON,
                func.length(func.trim(ExternalGroupRecord.external_id)) > 0,
                func.length(func.trim(ExternalGroupRecord.name)) > 0,
            ).all()
            catalog_groups.update({row.id: row for row in rows})

    catalog_scopes, catalog_scopes_truncated = _catalog_scopes(db)
    observed_scopes = {
        _scope_key(
            ticket.binding_id,
            ticket.external_source,
            ticket.external_workspace_id,
        )
        for ticket in trusted_tickets
    }
    all_scopes = sorted(
        set(catalog_scopes).union(observed_scopes),
        key=lambda item: (item[0], item[1], item[2] or ""),
    )
    scopes_truncated = catalog_scopes_truncated or len(all_scopes) > CATALOG_SCOPE_LIMIT
    all_scopes = all_scopes[:CATALOG_SCOPE_LIMIT]

    recommendations: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for scope in all_scopes:
        for resolver_code in AI_RESOLVER_TEAMS:
            bucket = scope_code_stats.get((scope, resolver_code), {
                "trusted": 0,
                "eligible": 0,
                "ambiguous": 0,
                "groups": {},
            })
            ranked = sorted(
                bucket["groups"].items(),
                key=lambda item: (-item[1]["tickets"], str(item[0])),
            )
            matched = sum(values["tickets"] for _group_id, values in ranked)
            top_group_id, top = ranked[0] if ranked else (None, {
                "tickets": 0,
                "direct": 0,
                "sole_membership": 0,
                "agents": set(),
            })
            runner_up_count = ranked[1][1]["tickets"] if len(ranked) > 1 else 0
            share = top["tickets"] / matched if matched else 0.0
            lead = (
                (top["tickets"] - runner_up_count) / matched
                if matched else 0.0
            )
            sample_adjusted_confidence = wilson_lower_bound(
                top["tickets"], matched
            )
            reason = (
                "evidence_truncated"
                if history_truncated or scopes_truncated
                else _abstention_reason(
                    trusted=bucket["trusted"],
                    eligible=bucket["eligible"],
                    matched=matched,
                    top_count=top["tickets"],
                    distinct_agents=len(top["agents"]),
                    share=share,
                    lead=lead,
                    confidence=sample_adjusted_confidence,
                )
            )
            common = {
                "resolver_code": resolver_code,
                "scope": _scope_payload(scope),
                "trusted_ticket_count": bucket["trusted"],
                "membership_eligible_ticket_count": bucket["eligible"],
                "unambiguous_ticket_count": matched,
                "ambiguous_membership_ticket_count": bucket["ambiguous"],
            }
            group = catalog_groups.get(top_group_id)
            group_scope = (
                _scope_key(group.binding_id, group.provider, group.workspace_id)
                if group is not None else None
            )
            if reason == "recommended" and group is not None and group_scope == scope:
                recommendations.append({
                    **common,
                    "provider_group_id": group.external_id,
                    "provider_group_name": group.name,
                    "evidence_ticket_count": top["tickets"],
                    "direct_assignment_ticket_count": top["direct"],
                    "sole_membership_ticket_count": top["sole_membership"],
                    "distinct_agent_count": len(top["agents"]),
                    "candidate_group_count": len(ranked),
                    "runner_up_ticket_count": runner_up_count,
                    "group_share": round(share, 3),
                    "confidence": round(
                        sample_adjusted_confidence, 3
                    ),
                    "runner_up_lead": round(lead, 3),
                    "evidence_coverage": round(
                        matched / bucket["trusted"] if bucket["trusted"] else 0.0,
                        3,
                    ),
                    "reason": (
                        f"{top['tickets']} of {matched} unambiguous trusted "
                        f"ticket assignments ({round(share * 100)}%) currently "
                        f"align to this group "
                        f"across {len(top['agents'])} provider agents; evidence "
                        f"includes {top['direct']} direct group assignments and "
                        f"{top['sole_membership']} unique-membership inferences."
                    ),
                    "advisory_only": True,
                })
            else:
                if reason == "recommended":
                    # A missing or cross-scope catalog row is never exposed as
                    # a placeholder recommendation.
                    reason = "catalog_group_unavailable"
                gaps.append({
                    **common,
                    "reason": reason,
                    "leading_ticket_count": top["tickets"],
                    "leading_distinct_agent_count": len(top["agents"]),
                    "candidate_group_count": len(ranked),
                })

    if not all_scopes:
        unmapped_codes = list(AI_RESOLVER_TEAMS)
    elif len(all_scopes) == 1:
        unmapped_codes = [gap["resolver_code"] for gap in gaps]
    else:
        unmapped_codes = []
    total_eligible = sum(
        bucket["eligible"] for bucket in scope_code_stats.values()
    )
    total_ambiguous = sum(
        bucket["ambiguous"] for bucket in scope_code_stats.values()
    )
    total_matched = sum(
        sum(group["tickets"] for group in bucket["groups"].values())
        for bucket in scope_code_stats.values()
    )
    return {
        "schema_version": "1",
        "generated_at": now,
        "window_start_at": since,
        "window_days": RECOMMENDATION_WINDOW_DAYS,
        "advisory_only": True,
        "mapping_applied": False,
        "no_mapping_applied": True,
        "thresholds": {
            "minimum_group_tickets": MIN_GROUP_TICKETS,
            "minimum_distinct_agents": MIN_DISTINCT_AGENTS,
            "minimum_top_share": MIN_TOP_SHARE,
            "minimum_runner_up_lead": MIN_RUNNER_UP_LEAD,
            "minimum_evidence_coverage": MIN_EVIDENCE_COVERAGE,
            "minimum_confidence": MIN_CONFIDENCE,
            "history_ticket_limit": history_limit,
        },
        "coverage": {
            "candidate_ticket_count": len(history),
            "analyzed_ticket_count": len(history),
            "trusted_route_ticket_count": len(trusted_tickets),
            "membership_eligible_ticket_count": total_eligible,
            "unambiguous_ticket_count": total_matched,
            "ambiguous_membership_ticket_count": total_ambiguous,
            "without_membership_evidence_ticket_count": (
                len(trusted_tickets) - total_eligible
            ),
            "excluded_ambiguous_or_unmatched_ticket_count": (
                len(trusted_tickets) - total_matched
            ),
            "history_truncated": history_truncated,
            "catalog_scopes_truncated": scopes_truncated,
        },
        "ready": bool(recommendations),
        "scopes": [_scope_payload(scope) for scope in all_scopes],
        "recommendations": recommendations,
        "scoped_gaps": gaps,
        "unmapped_codes": unmapped_codes,
        "unmapped_codes_scope": (
            _scope_payload(all_scopes[0]) if len(all_scopes) == 1 else None
        ),
    }


def _agent_mapping_history_candidates(
    db: Session,
    *,
    since: datetime,
    through: datetime,
    history_limit: int,
) -> tuple[list[TicketRecord], bool]:
    """Load a bounded history whose current AI route can classify an owner."""
    observed_at = func.coalesce(
        TicketRecord.external_updated_at,
        TicketRecord.updated_at,
        TicketRecord.created_at,
    )
    rows = db.query(TicketRecord).options(load_only(
        TicketRecord.id,
        TicketRecord.assignee_id,
        TicketRecord.binding_id,
        TicketRecord.external_source,
        TicketRecord.external_assignee_id,
        TicketRecord.subject,
        TicketRecord.description,
        TicketRecord.reporter,
        TicketRecord.external_requester_email,
        TicketRecord.external_conversation_text,
        TicketRecord.external_category,
        TicketRecord.external_subcategory,
        TicketRecord.external_item_category,
        TicketRecord.ai_suggested_team,
        TicketRecord.ai_secondary_team,
        TicketRecord.ai_routing_confidence,
        TicketRecord.ai_routing_scope,
        TicketRecord.ai_affected_service,
        TicketRecord.ai_failure_domain,
        TicketRecord.ai_routing_reason,
        TicketRecord.ai_routing_input_hash,
        TicketRecord.external_updated_at,
        TicketRecord.updated_at,
        TicketRecord.created_at,
    )).filter(
        (TicketRecord.assignee_id.isnot(None))
        | (
            TicketRecord.external_assignee_id.isnot(None)
            & (TicketRecord.external_assignee_id != "")
        ),
        TicketRecord.ai_suggested_team.in_(AI_RESOLVER_TEAMS),
        TicketRecord.ai_routing_input_hash.isnot(None),
        observed_at >= since,
        observed_at <= through,
    ).order_by(
        observed_at.desc(),
        TicketRecord.id.asc(),
    ).limit(history_limit + 1).all()
    return rows[:history_limit], len(rows) > history_limit


def _agent_subject_identity_maps(
    db: Session,
    tickets: Collection[TicketRecord],
) -> tuple[
    dict[tuple[str, str, str], tuple[Optional[str], Optional[str]]],
    dict[str, tuple[Optional[str], str]],
]:
    """Resolve provider/local assignees to canonical people without guessing."""
    external_keys = {
        (
            str(ticket.binding_id or "legacy"),
            str(ticket.external_source or "").lower(),
            str(ticket.external_assignee_id),
        )
        for ticket in tickets
        if ticket.external_source and ticket.external_assignee_id
    }
    external_records: dict[tuple[str, str, str], ExternalUserRecord] = {}
    if external_keys:
        rows = db.query(ExternalUserRecord).filter(
            ExternalUserRecord.binding_id.in_({key[0] for key in external_keys}),
            func.lower(ExternalUserRecord.provider).in_({key[1] for key in external_keys}),
            ExternalUserRecord.external_id.in_({key[2] for key in external_keys}),
            func.lower(ExternalUserRecord.user_type) == "agent",
            ExternalUserRecord.active.is_(True),
        ).all()
        external_records = {
            (row.binding_id, row.provider.lower(), row.external_id): row
            for row in rows
            if (row.binding_id, row.provider.lower(), row.external_id) in external_keys
        }

    external_record_ids = {row.id for row in external_records.values()}
    person_by_external: dict[str, str] = {}
    legacy_user_by_external: dict[str, str] = {}
    if external_record_ids:
        person_by_external = dict(db.query(
            DirectoryPersonExternalIdentityRecord.external_user_id,
            DirectoryPersonExternalIdentityRecord.person_id,
        ).filter(
            DirectoryPersonExternalIdentityRecord.external_user_id.in_(external_record_ids),
            DirectoryPersonExternalIdentityRecord.link_state == "active",
        ).all())
        legacy_user_by_external = dict(db.query(
            UserExternalIdentityLinkRecord.external_user_id,
            UserExternalIdentityLinkRecord.user_id,
        ).filter(
            UserExternalIdentityLinkRecord.external_user_id.in_(external_record_ids),
        ).all())

    local_user_ids = {
        ticket.assignee_id for ticket in tickets if ticket.assignee_id
    }.union(legacy_user_by_external.values())
    person_ids = set(person_by_external.values())
    local_rows = []
    if local_user_ids or person_ids:
        local_query = db.query(
            DirectoryPersonLocalAccountRecord.person_id,
            DirectoryPersonLocalAccountRecord.user_id,
        )
        filters = []
        if local_user_ids:
            filters.append(
                DirectoryPersonLocalAccountRecord.user_id.in_(local_user_ids)
            )
        if person_ids:
            filters.append(
                DirectoryPersonLocalAccountRecord.person_id.in_(person_ids)
            )
        local_rows = local_query.filter(filters[0] if len(filters) == 1 else (
            filters[0] | filters[1]
        )).all()
    person_by_user = {user_id: person_id for person_id, user_id in local_rows}
    user_by_person = {person_id: user_id for person_id, user_id in local_rows}

    operational_user_ids = {
        row[0] for row in db.query(UserRecord.id).filter(
            UserRecord.id.in_(local_user_ids.union(user_by_person.values()))
            if local_user_ids or user_by_person
            else UserRecord.id.in_([]),
            UserRecord.is_active.is_(True),
            func.lower(UserRecord.role).in_(("admin", "supervisor", "agent")),
        ).all()
    }

    external_subjects: dict[
        tuple[str, str, str], tuple[Optional[str], Optional[str]]
    ] = {}
    for key, external in external_records.items():
        person_id = person_by_external.get(external.id)
        user_id = user_by_person.get(person_id) if person_id else None
        if user_id not in operational_user_ids:
            legacy_user = legacy_user_by_external.get(external.id)
            user_id = legacy_user if legacy_user in operational_user_ids else None
        if person_id or user_id:
            external_subjects[key] = (person_id, user_id)

    local_subjects: dict[str, tuple[Optional[str], str]] = {}
    for user_id in operational_user_ids:
        local_subjects[user_id] = (person_by_user.get(user_id), user_id)
    return external_subjects, local_subjects


def recommend_agent_team_mappings(
    db: Session,
    *,
    pipeline_version: str,
    model: str,
    allow_synthetic: bool,
    input_hash_for_ticket: Callable[[TicketRecord], str],
    generated_at: Optional[datetime] = None,
    history_limit: int = HISTORY_TICKET_LIMIT,
    window_days: int = AGENT_RECOMMENDATION_WINDOW_DAYS,
) -> dict[str, Any]:
    """Recommend one reviewable resolver team per agent from trusted AI history."""
    if history_limit < 1 or history_limit > HISTORY_TICKET_LIMIT:
        raise ValueError("history_limit is outside the bounded recommendation policy")
    if not (
        MIN_AGENT_RECOMMENDATION_WINDOW_DAYS
        <= window_days
        <= MAX_AGENT_RECOMMENDATION_WINDOW_DAYS
    ):
        raise ValueError("window_days is outside the bounded recommendation policy")
    now = generated_at or datetime.utcnow()
    since = now - timedelta(days=window_days)
    history, history_truncated = _agent_mapping_history_candidates(
        db,
        since=since,
        through=now,
        history_limit=history_limit,
    )
    trusted_ids = current_route_artifact_ticket_ids(
        db,
        history,
        pipeline_version=pipeline_version,
        model=model,
        allow_synthetic=allow_synthetic,
        input_hash_for_ticket=input_hash_for_ticket,
        require_unique_active_artifact=True,
    )
    trusted_tickets = [ticket for ticket in history if ticket.id in trusted_ids]
    external_subjects, local_subjects = _agent_subject_identity_maps(
        db, trusted_tickets
    )

    stats: dict[tuple[str, str], dict[str, Any]] = {}
    attributed = 0
    ambiguous = 0
    for ticket in trusted_tickets:
        local_subject = local_subjects.get(ticket.assignee_id or "")
        external_subject = external_subjects.get((
            str(ticket.binding_id or "legacy"),
            str(ticket.external_source or "").lower(),
            str(ticket.external_assignee_id or ""),
        ))
        subjects = [subject for subject in (local_subject, external_subject) if subject]
        if not subjects:
            continue
        canonical_keys = {
            ("person", subject[0]) if subject[0] else ("user", subject[1])
            for subject in subjects
        }
        if len(canonical_keys) != 1:
            ambiguous += 1
            continue
        subject = external_subject or local_subject
        assert subject is not None
        person_id, user_id = subject
        key = next(iter(canonical_keys))
        bucket = stats.setdefault(key, {
            "person_id": person_id,
            "user_id": user_id,
            "groups": Counter(),
            "latest_ticket_at": None,
        })
        if bucket["user_id"] is None and user_id is not None:
            bucket["user_id"] = user_id
        bucket["groups"][ticket.ai_suggested_team] += 1
        observed_at = (
            ticket.external_updated_at or ticket.updated_at or ticket.created_at
        )
        if observed_at is not None and (
            bucket["latest_ticket_at"] is None
            or observed_at > bucket["latest_ticket_at"]
        ):
            bucket["latest_ticket_at"] = observed_at
        attributed += 1

    recommendations: list[dict[str, Any]] = []
    for key, bucket in sorted(stats.items()):
        ranked = sorted(
            bucket["groups"].items(),
            key=lambda item: (-item[1], item[0]),
        )
        total = sum(bucket["groups"].values())
        top_group, top_count = ranked[0]
        runner_up_count = ranked[1][1] if len(ranked) > 1 else 0
        share = top_count / total
        lead = (top_count - runner_up_count) / total
        confidence = wilson_lower_bound(top_count, total)
        if (
            total < MIN_AGENT_HISTORY_TICKETS
            or top_count < MIN_AGENT_HISTORY_TICKETS
            or share < MIN_AGENT_TOP_SHARE
            or lead < MIN_AGENT_RUNNER_UP_LEAD
            or confidence < MIN_AGENT_CONFIDENCE
        ):
            continue
        recommendations.append({
            "subject_key": f"{key[0]}:{key[1]}",
            "person_id": bucket["person_id"],
            "user_id": bucket["user_id"],
            "resolver_group": top_group,
            "confidence": round(confidence, 3),
            "group_share": round(share, 3),
            "evidence_ticket_count": top_count,
            "total_trusted_ticket_count": total,
            "runner_up_ticket_count": runner_up_count,
            "latest_ticket_at": bucket["latest_ticket_at"],
            "reason": (
                f"{top_count} of {total} trusted AI-routed ticket assignments "
                f"({round(share * 100)}%) align to {top_group}."
            ),
            "advisory_only": True,
        })

    return {
        "schema_version": "1",
        "generated_at": now,
        "window_start_at": since,
        "window_days": window_days,
        "advisory_only": True,
        "mapping_applied": False,
        "thresholds": {
            "minimum_history_tickets": MIN_AGENT_HISTORY_TICKETS,
            "minimum_top_share": MIN_AGENT_TOP_SHARE,
            "minimum_runner_up_lead": MIN_AGENT_RUNNER_UP_LEAD,
            "minimum_confidence": MIN_AGENT_CONFIDENCE,
            "history_ticket_limit": history_limit,
        },
        "coverage": {
            "candidate_ticket_count": len(history),
            "trusted_route_ticket_count": len(trusted_tickets),
            "attributed_ticket_count": attributed,
            "ambiguous_identity_ticket_count": ambiguous,
            "unmatched_ticket_count": len(trusted_tickets) - attributed - ambiguous,
            "analyzed_subject_count": len(stats),
            "recommended_subject_count": len(recommendations),
            "history_truncated": history_truncated,
        },
        "ready": bool(recommendations),
        "recommendations": recommendations,
    }
