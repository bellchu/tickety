import os
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .database import (
    SessionLocal, TicketRecord, UserRecord, RecognitionRecord,
    UserMappingRecord, SyncStateRecord,
)

USERS = [
    {
        "id": "u-alice",
        "name": "Alice Chen",
        "email": "alice@company.com",
        "avatar": None,
        "title": "Senior Support Engineer",
    },
    {
        "id": "u-bob",
        "name": "Bob Martinez",
        "email": "bob@company.com",
        "avatar": None,
        "title": "Support Engineer",
    },
    {
        "id": "u-carol",
        "name": "Carol Singh",
        "email": "carol@company.com",
        "avatar": None,
        "title": "Support Lead",
    },
]

USER_MAPPINGS = [
    {"tickety_user_id": "u-alice", "external_assignee_id": "1001"},
    {"tickety_user_id": "u-bob", "external_assignee_id": "1002"},
    {"tickety_user_id": "u-carol", "external_assignee_id": "1003"},
]

TICKETS = [
    {
        "id": "t-001", "external_id": "101", "subject": "VPN connection drops every 10 minutes",
        "description": "My VPN keeps disconnecting while I'm on important calls. This is urgent.",
        "reporter": "jdoe@company.com", "priority": "P1", "status": "Closed",
        "external_status": "Closed", "external_assignee_id": "1001",
        "resolved_by": "u-alice", "resolved_at": datetime.utcnow() - timedelta(days=2, hours=3),
        "sentiment": "Business-Critical", "mood": "urgent", "category": "Network",
        "complexity": 5, "points_awarded": 50,
        "ai_reasoning": "sentiment: Business-Critical, category: Network, priority: P1, mood: urgent, action: escalate | Reasoning: VPN instability affecting business calls.",
    },
    {
        "id": "t-002", "external_id": "102", "subject": "Cannot access Salesforce",
        "description": "I get a 403 error when trying to log into Salesforce.",
        "reporter": "mwong@company.com", "priority": "P2", "status": "Closed",
        "external_status": "Closed", "external_assignee_id": "1002",
        "resolved_by": "u-bob", "resolved_at": datetime.utcnow() - timedelta(days=1, hours=6),
        "sentiment": "Moderate", "mood": "concerned", "category": "Access Request",
        "complexity": 3, "points_awarded": 30,
        "ai_reasoning": "sentiment: Moderate, category: Access Request, priority: P2, mood: concerned, action: respond | Reasoning: Access issue likely permissions.",
    },
    {
        "id": "t-003", "external_id": "103", "subject": "Laptop screen flickering",
        "description": "My laptop screen flickers after the recent update.",
        "reporter": "rkhan@company.com", "priority": "P2", "status": "Open",
        "external_status": "Open", "external_assignee_id": "1001",
        "sentiment": "Neutral", "mood": "neutral", "category": "Hardware",
        "complexity": 3,
        "ai_reasoning": "sentiment: Neutral, category: Hardware, priority: P2, mood: neutral, action: route | Reasoning: Hardware display issue post-update.",
    },
    {
        "id": "t-004", "external_id": "104", "subject": "Request: new monitor for home office",
        "description": "I'd like to request a second monitor for my home office setup.",
        "reporter": "lsmith@company.com", "priority": "P3", "status": "Closed",
        "external_status": "Closed", "external_assignee_id": "1003",
        "resolved_by": "u-carol", "resolved_at": datetime.utcnow() - timedelta(hours=18),
        "sentiment": "Positive", "mood": "satisfied", "category": "Hardware",
        "complexity": 1, "points_awarded": 15,
        "ai_reasoning": "sentiment: Positive, category: Hardware, priority: P3, mood: satisfied, action: respond | Reasoning: Standard hardware request.",
    },
    {
        "id": "t-005", "external_id": "105", "subject": "Email signature not updating",
        "description": "I changed my email signature but it's not showing on outgoing emails.",
        "reporter": "tpark@company.com", "priority": "P3", "status": "Open",
        "external_status": "Open", "external_assignee_id": "1002",
        "sentiment": "Neutral", "mood": "neutral", "category": "Software",
        "complexity": 2,
        "ai_reasoning": "sentiment: Neutral, category: Software, priority: P3, mood: neutral, action: respond | Reasoning: Outlook signature sync issue.",
    },
    {
        "id": "t-006", "external_id": "106", "subject": "URGENT: Production database down",
        "description": "The main production database is not responding. All operations are halted!",
        "reporter": "dba@company.com", "priority": "P1", "status": "Escalated",
        "external_status": "Escalated", "external_assignee_id": "1003",
        "sentiment": "Business-Critical", "mood": "critical", "category": "Software",
        "complexity": 5,
        "ai_reasoning": "sentiment: Business-Critical, category: Software, priority: P1, mood: critical, action: escalate | Reasoning: Critical production outage.",
    },
    {
        "id": "t-007", "external_id": "107", "subject": "Password reset for Active Directory",
        "description": "I'm locked out of my account and need a password reset.",
        "reporter": "nguyen@company.com", "priority": "P3", "status": "Closed",
        "external_status": "Closed", "external_assignee_id": "1001",
        "resolved_by": "u-alice", "resolved_at": datetime.utcnow() - timedelta(hours=5),
        "sentiment": "Moderate", "mood": "concerned", "category": "Access Request",
        "complexity": 1, "points_awarded": 15,
        "ai_reasoning": "sentiment: Moderate, category: Access Request, priority: P3, mood: concerned, action: respond | Reasoning: Standard password reset.",
    },
    {
        "id": "t-008", "external_id": "108", "subject": "Slack notifications not working on mobile",
        "description": "I stopped getting Slack push notifications on my phone since yesterday.",
        "reporter": "jlee@company.com", "priority": "P3", "status": "Open",
        "external_status": "Open", "external_assignee_id": "1002",
        "sentiment": "Neutral", "mood": "neutral", "category": "Software",
        "complexity": 2,
        "ai_reasoning": "sentiment: Neutral, category: Software, priority: P3, mood: neutral, action: respond | Reasoning: Mobile push notification config.",
    },
    {
        "id": "t-009", "external_id": "109", "subject": "New laptop setup - onboarding",
        "description": "I'm joining the team Monday and need my laptop configured.",
        "reporter": "newbie@company.com", "priority": "P2", "status": "Awaiting Review",
        "external_status": "Pending", "external_assignee_id": "1003",
        "sentiment": "Positive", "mood": "satisfied", "category": "Hardware",
        "complexity": 2,
        "ai_reasoning": "sentiment: Positive, category: Hardware, priority: P2, mood: satisfied, action: route | Reasoning: New hire onboarding.",
    },
    {
        "id": "t-010", "external_id": "110", "subject": "Printer on floor 3 not working",
        "description": "The shared printer on the 3rd floor is showing an error code.",
        "reporter": "floor3@company.com", "priority": "P3", "status": "Closed",
        "external_status": "Closed", "external_assignee_id": "1001",
        "resolved_by": "u-alice", "resolved_at": datetime.utcnow() - timedelta(hours=2),
        "sentiment": "Neutral", "mood": "neutral", "category": "Hardware",
        "complexity": 2, "points_awarded": 15,
        "ai_reasoning": "sentiment: Neutral, category: Hardware, priority: P3, mood: neutral, action: route | Reasoning: Shared printer hardware fault.",
    },
    {
        "id": "t-011", "external_id": "111", "subject": "Can't connect to office Wi-Fi",
        "description": "My phone won't connect to the corporate Wi-Fi. It says 'IP configuration failed'.",
        "reporter": "pgarcia@company.com", "priority": "P2", "status": "Open",
        "external_status": "Open", "external_assignee_id": "1002",
        "sentiment": "High-Impact", "mood": "urgent", "category": "Network",
        "complexity": 3,
        "ai_reasoning": "sentiment: High-Impact, category: Network, priority: P2, mood: urgent, action: respond | Reasoning: Wi-Fi DHCP/IP config issue.",
    },
    {
        "id": "t-012", "external_id": "112", "subject": "Request: Adobe Creative Cloud license",
        "description": "I need an Adobe CC license for a new design project starting next week.",
        "reporter": "design@company.com", "priority": "P3", "status": "Closed",
        "external_status": "Closed", "external_assignee_id": "1003",
        "resolved_by": "u-carol", "resolved_at": datetime.utcnow() - timedelta(days=3),
        "sentiment": "Positive", "mood": "satisfied", "category": "Access Request",
        "complexity": 1, "points_awarded": 15,
        "ai_reasoning": "sentiment: Positive, category: Access Request, priority: P3, mood: satisfied, action: respond | Reasoning: Software license request.",
    },
    {
        "id": "t-013", "external_id": "113", "subject": "Outlook crashes on startup",
        "description": "Every time I open Outlook it crashes within 5 seconds. I've tried restarting.",
        "reporter": "hrossi@company.com", "priority": "P2", "status": "Escalated",
        "external_status": "Escalated", "external_assignee_id": "1001",
        "sentiment": "High-Impact", "mood": "urgent", "category": "Software",
        "complexity": 4,
        "ai_reasoning": "sentiment: High-Impact, category: Software, priority: P2, mood: urgent, action: escalate | Reasoning: Recurring Outlook crash.",
    },
    {
        "id": "t-014", "external_id": "114", "subject": "How do I set up dual-factor authentication?",
        "description": "I want to enable 2FA on my account but I'm not sure how.",
        "reporter": "curious@company.com", "priority": "P3", "status": "Open",
        "external_status": "Open", "external_assignee_id": "1002",
        "sentiment": "Positive", "mood": "neutral", "category": "Access Request",
        "complexity": 1,
        "ai_reasoning": "sentiment: Positive, category: Access Request, priority: P3, mood: neutral, action: respond | Reasoning: Self-service 2FA guidance.",
    },
    {
        "id": "t-015", "external_id": "115", "subject": "Shared drive access for new team member",
        "description": "Please grant shared drive access to our new team member who started today.",
        "reporter": "manager@company.com", "priority": "P2", "status": "Closed",
        "external_status": "Closed", "external_assignee_id": "1003",
        "resolved_by": "u-carol", "resolved_at": datetime.utcnow() - timedelta(hours=12),
        "sentiment": "Neutral", "mood": "neutral", "category": "Access Request",
        "complexity": 2, "points_awarded": 30,
        "ai_reasoning": "sentiment: Neutral, category: Access Request, priority: P2, mood: neutral, action: respond | Reasoning: Standard access provisioning.",
    },
]

RECOGNITIONS_SEED = [
    {"user_id": "u-alice", "recognition_key": "first_resolution"},
    {"user_id": "u-alice", "recognition_key": "consistent_performer"},
    {"user_id": "u-bob", "recognition_key": "first_resolution"},
    {"user_id": "u-carol", "recognition_key": "first_resolution"},
    {"user_id": "u-carol", "recognition_key": "reliability_streak"},
]


def run_seed():
    db: Session = SessionLocal()
    try:
        if db.query(UserRecord).count() > 0 and db.query(TicketRecord).count() > 0:
            print("Seed: data already exists, skipping.")
            return

        # Clean partial data
        db.query(RecognitionRecord).delete()
        db.query(TicketRecord).delete()
        db.query(UserMappingRecord).delete()
        db.query(UserRecord).delete()
        db.query(SyncStateRecord).delete()
        db.commit()

        # Users
        for u in USERS:
            db.add(UserRecord(
                id=u["id"], name=u["name"], email=u["email"],
                avatar=u["avatar"], title=u["title"],
                impact_points=0, tier=1, momentum=0,
            ))
        db.flush()

        # User mappings
        for m in USER_MAPPINGS:
            db.add(UserMappingRecord(
                tickety_user_id=m["tickety_user_id"],
                external_source="freshservice",
                external_assignee_id=m["external_assignee_id"],
            ))
        db.flush()

        # Sync state
        db.add(SyncStateRecord(provider="freshservice", last_status="idle", total_synced=0))
        db.flush()

        # Tickets
        for t in TICKETS:
            url = f"https://yourdomain.freshservice.com/support/tickets/{t['external_id']}"
            db.add(TicketRecord(
                id=t["id"],
                subject=t["subject"],
                description=t["description"],
                reporter=t["reporter"],
                status=t["status"],
                priority=t["priority"],
                sentiment=t.get("sentiment"),
                category=t.get("category"),
                mood=t.get("mood"),
                complexity=t.get("complexity", 1),
                ai_reasoning=t.get("ai_reasoning"),
                external_source="freshservice",
                external_id=t["external_id"],
                external_url=url,
                external_status=t.get("external_status"),
                external_assignee_id=t.get("external_assignee_id"),
                resolved_by=t.get("resolved_by"),
                resolved_at=t.get("resolved_at"),
                points_awarded=t.get("points_awarded", 0),
                points_awarded_sent=True,
            ))
        db.flush()

        # Recalculate user impact points from resolved tickets
        for u in USERS:
            resolved = db.query(TicketRecord).filter(
                TicketRecord.resolved_by == u["id"],
                TicketRecord.points_awarded > 0,
            ).all()
            total = sum(t.points_awarded for t in resolved)
            user = db.query(UserRecord).filter(UserRecord.id == u["id"]).first()
            if not user:
                continue
            user.impact_points = total
            user.momentum = len(resolved)
            user.last_action_at = max(
                (t.resolved_at for t in resolved if t.resolved_at),
                default=datetime.utcnow(),
            )
            # Tier
            for i in range(len([0, 100, 250, 500, 1000, 2000, 4000, 8000]) - 1, -1, -1):
                if total >= [0, 100, 250, 500, 1000, 2000, 4000, 8000][i]:
                    user.tier = i + 1 if i > 0 else 1
                    break

        # Recognitions
        for r in RECOGNITIONS_SEED:
            db.add(RecognitionRecord(
                user_id=r["user_id"],
                recognition_key=r["recognition_key"],
            ))

        db.commit()
        print(f"Seed: inserted {len(USERS)} users, {len(TICKETS)} tickets, {len(RECOGNITIONS_SEED)} recognitions.")
    except Exception as e:
        db.rollback()
        print(f"Seed error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run_seed()