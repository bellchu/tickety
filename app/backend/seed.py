import os
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .database import (
    SessionLocal, TicketRecord, UserRecord, RecognitionRecord,
    UserMappingRecord, SyncStateRecord, TicketCategoryRecord,
    KbArticleRecord, TicketStatusConfigRecord, TicketPriorityConfigRecord,
    NotificationConfigRecord,
    ProjectRecord, ServiceItemRecord, ServiceRequestRecord,
    ProblemRecord, ProblemTicketLinkRecord,
    ChangeRecord, ChangeApprovalRecord,
    AssetRecord, SurveyTemplateRecord,
)

import hashlib


def _hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

USERS = [
    {
        "id": "u-alice",
        "name": "Alice Chen",
        "email": "alice@company.com",
        "avatar": None,
        "title": "Senior Support Engineer",
        "role": "admin",
        "password": "tickety123",
    },
    {
        "id": "u-bob",
        "name": "Bob Martinez",
        "email": "bob@company.com",
        "avatar": None,
        "title": "Support Engineer",
        "role": "agent",
        "password": "tickety123",
    },
    {
        "id": "u-carol",
        "name": "Carol Singh",
        "email": "carol@company.com",
        "avatar": None,
        "title": "Support Lead",
        "role": "supervisor",
        "password": "tickety123",
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
                role=u.get("role", "agent"),
                password_hash=_hash_pw(u["password"]),
                impact_points=0, tier=1, momentum=0,
            ))
        db.flush()

        # User mappings
        for m in USER_MAPPINGS:
            db.add(UserMappingRecord(
                tickety_user_id=m["tickety_user_id"],
                external_source="standalone",
                external_assignee_id=m["external_assignee_id"],
            ))
        db.flush()

        # Sync state
        db.add(SyncStateRecord(provider="standalone", last_status="idle", total_synced=0))
        db.flush()

        # Tickets
        for t in TICKETS:
            url = f"https://yourdomain.example.com/support/tickets/{t['external_id']}"
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
                external_source="standalone",
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

        # Default categories
        if db.query(TicketCategoryRecord).count() == 0:
            for cat in [
                {"name": "Network", "description": "Network connectivity issues", "color": "blue"},
                {"name": "Hardware", "description": "Physical equipment issues", "color": "amber"},
                {"name": "Software", "description": "Application and OS issues", "color": "emerald"},
                {"name": "Access", "description": "Account and permission requests", "color": "violet"},
                {"name": "Email", "description": "Email and communication issues", "color": "cyan"},
                {"name": "Other", "description": "Miscellaneous issues", "color": "slate"},
            ]:
                db.add(TicketCategoryRecord(**cat))
            db.commit()
            print("Seed: inserted 6 default categories.")

        # Default ticket statuses
        if db.query(TicketStatusConfigRecord).count() == 0:
            for i, s in enumerate([
                {"name": "New", "label": "New", "color": "blue", "is_open": True, "is_terminal": False, "sort_order": 0},
                {"name": "Open", "label": "Open", "color": "blue", "is_open": True, "is_terminal": False, "sort_order": 1},
                {"name": "Awaiting Review", "label": "Awaiting Review", "color": "amber", "is_open": True, "is_terminal": False, "sort_order": 2},
                {"name": "Escalated", "label": "Escalated", "color": "red", "is_open": True, "is_terminal": False, "sort_order": 3},
                {"name": "Processed", "label": "Processed", "color": "emerald", "is_open": True, "is_terminal": False, "sort_order": 4},
                {"name": "Resolved", "label": "Resolved", "color": "moss", "is_open": False, "is_terminal": True, "sort_order": 5},
                {"name": "Closed", "label": "Closed", "color": "slate", "is_open": False, "is_terminal": True, "sort_order": 6},
            ]):
                db.add(TicketStatusConfigRecord(**s))
            db.commit()
            print("Seed: inserted 7 default ticket statuses.")

        # Default priorities
        if db.query(TicketPriorityConfigRecord).count() == 0:
            for p in [
                {"name": "P1", "label": "Critical", "color": "red", "sla_hours": 4, "weight": 1, "sort_order": 0},
                {"name": "P2", "label": "High", "color": "amber", "sla_hours": 24, "weight": 5, "sort_order": 1},
                {"name": "P3", "label": "Normal", "color": "blue", "sla_hours": 72, "weight": 10, "sort_order": 2},
                {"name": "P4", "label": "Low", "color": "slate", "sla_hours": 168, "weight": 20, "sort_order": 3},
            ]:
                db.add(TicketPriorityConfigRecord(**p))
            db.commit()
            print("Seed: inserted 4 default priorities.")

        # Default notification config
        if db.query(NotificationConfigRecord).count() == 0:
            for n in [
                {"event": "new_ticket", "label": "New Ticket Created", "enabled": True, "channels": "in_app"},
                {"event": "sla_breach", "label": "SLA Breach", "enabled": True, "channels": "in_app,email"},
                {"event": "sla_at_risk", "label": "SLA At Risk", "enabled": True, "channels": "in_app"},
                {"event": "escalation", "label": "Ticket Escalated", "enabled": True, "channels": "in_app,email"},
                {"event": "resolution", "label": "Ticket Resolved", "enabled": True, "channels": "in_app"},
                {"event": "assignment", "label": "Ticket Assigned to You", "enabled": True, "channels": "in_app,email"},
                {"event": "comment", "label": "New Comment on Ticket", "enabled": True, "channels": "in_app"},
            ]:
                db.add(NotificationConfigRecord(**n))
            db.commit()
            print("Seed: inserted 7 notification configs.")

        # Default KB articles
        if db.query(KbArticleRecord).count() == 0:
            kb_articles = [
                {"id": "kb-vpn", "title": "How to Reset Your VPN Connection",
                 "content": "If your VPN keeps disconnecting:\n\n1. Restart the VPN client\n2. Ensure you are connected to corporate Wi-Fi\n3. Click **Reconnect**\n4. If the issue persists, restart your computer\n5. Contact IT if it still fails after a reboot\n\nCommon causes: outdated VPN client, network firewall rules, or DNS resolution issues.",
                 "category": "Network", "tags": "vpn,network,connection", "status": "published"},
                {"id": "kb-2fa", "title": "Setting Up Two-Factor Authentication (2FA)",
                 "content": "To enable 2FA on your account:\n\n1. Log in to the account portal\n2. Go to **Security** > **Two-Factor Authentication**\n3. Choose your preferred method (authenticator app recommended)\n4. Scan the QR code with your app\n5. Enter the 6-digit code to confirm\n6. Save your backup codes in a secure location\n\nYou will need 2FA for all future logins.",
                 "category": "Access", "tags": "2fa,security,authentication", "status": "published"},
                {"id": "kb-pwd", "title": "Password Reset for Active Directory",
                 "content": "If you are locked out of your account:\n\n1. Use the self-service portal at reset.company.com\n2. Enter your email and verify via SMS\n3. Set a new password (must meet complexity requirements)\n4. Wait 5 minutes for sync to complete\n\nIf self-service fails, call the IT helpdesk at ext. 4357.",
                 "category": "Access", "tags": "password,reset,active-directory", "status": "published"},
                {"id": "kb-outlook", "title": "Fixing Outlook Crashes on Startup",
                 "content": "If Outlook crashes within seconds of opening:\n\n1. Open **Control Panel** > **Programs and Features**\n2. Right-click Microsoft Office > **Change** > **Quick Repair**\n3. If that fails, try **Online Repair**\n4. Create a new Outlook profile: Control Panel > Mail > Show Profiles > Add\n5. Reconfigure your email account in the new profile\n\nThis is usually caused by a corrupted profile or add-in conflict.",
                 "category": "Software", "tags": "outlook,crash,office", "status": "published"},
                {"id": "kb-wifi", "title": "Connecting to Corporate Wi-Fi",
                 "content": "To connect to corporate Wi-Fi:\n\n1. Select **CorpSecure** from available networks\n2. Enter your domain credentials (username@company.com)\n3. Accept the certificate prompt\n4. Wait for the connection to establish (10-15 seconds)\n\nIf you get 'IP configuration failed':\n- Forget the network and reconnect\n- Restart your device\n- Check that DHCP is enabled on your adapter",
                 "category": "Network", "tags": "wifi,network,connection", "status": "published"},
                {"id": "kb-license", "title": "Requesting Software Licenses",
                 "content": "To request a new software license:\n\n1. Submit a ticket with category 'Access Request'\n2. Include the software name and justification\n3. Your manager must approve the request\n4. IT will provision the license within 2 business days\n\nCommon licenses: Adobe CC, Microsoft 365, JetBrains, Slack Plus.",
                 "category": "Access", "tags": "license,software,request", "status": "published"},
                {"id": "kb-onboard", "title": "New Employee IT Onboarding Checklist",
                 "content": "IT onboarding steps for new hires:\n\n1. **Before Day 1**: Laptop is imaged and configured\n2. **Day 1**: Account creation, email setup, VPN access\n3. **Day 2**: Software installation, peripheral setup\n4. **Day 3**: Training on IT tools and security policies\n5. **Week 1**: 2FA setup, password manager install, access review\n\nNew hires should submit any issues through the ticketing system.",
                 "category": "Other", "tags": "onboarding,new-hire,setup", "status": "published"},
            ]
            for a in kb_articles:
                db.add(KbArticleRecord(
                    id=a["id"], title=a["title"],
                    slug=a["id"].replace("kb-", ""),
                    content=a["content"], category=a["category"],
                    tags=a["tags"], status=a["status"],
                ))
            db.commit()
            print(f"Seed: inserted {len(kb_articles)} KB articles.")

        # Default projects
        if db.query(ProjectRecord).count() == 0:
            for proj in [
                {"id": "proj-it", "name": "IT Support", "key": "IT", "description": "General IT support and incident management", "lead_id": "u-alice"},
                {"id": "proj-ops", "name": "Infrastructure Ops", "key": "OPS", "description": "Server, network, and cloud infrastructure", "lead_id": "u-carol"},
            ]:
                db.add(ProjectRecord(**proj))
            db.commit()
            print("Seed: inserted 2 projects.")

        # Default service catalog items
        if db.query(ServiceItemRecord).count() == 0:
            for svc in [
                {"id": "svc-laptop", "name": "New Laptop Setup", "description": "Request a new laptop configured with corporate image.", "category": "Hardware", "sla_hours": 48, "approval_required": True},
                {"id": "svc-monitor", "name": "Second Monitor Request", "description": "Request an additional monitor for your workstation.", "category": "Hardware", "sla_hours": 72},
                {"id": "svc-license", "name": "Software License Request", "description": "Request a new software license (Adobe CC, JetBrains, etc).", "category": "Software", "sla_hours": 24, "approval_required": True},
                {"id": "svc-access", "name": "Access Provisioning", "description": "Request access to a shared drive, folder, or system.", "category": "Access", "sla_hours": 4},
                {"id": "svc-onboard", "name": "New Employee Onboarding", "description": "IT onboarding for new hires: accounts, laptop, training.", "category": "Other", "sla_hours": 120, "approval_required": True},
                {"id": "svc-vpn", "name": "VPN Access Request", "description": "Request VPN access for remote work.", "category": "Network", "sla_hours": 8},
            ]:
                db.add(ServiceItemRecord(**svc))
            db.commit()
            print("Seed: inserted 6 service catalog items.")

        # Default problems
        if db.query(ProblemRecord).count() == 0:
            prob = ProblemRecord(
                id="prob-vpn", title="Intermittent VPN disconnections affecting multiple users",
                description="Multiple reports of VPN dropping every 10-30 minutes across different departments.",
                status="Investigating", priority="P1", category="Network",
                assigned_to="u-alice", impact_scope="All remote workers on CorpVPN",
                workaround="Switch to backup VPN (BackupCorpVPN) while investigating.",
            )
            db.add(prob)
            db.flush()
            # Link related incident tickets
            for tid in ["t-001", "t-011"]:
                db.add(ProblemTicketLinkRecord(problem_id="prob-vpn", ticket_id=tid))
            db.commit()
            print("Seed: inserted 1 problem with 2 linked tickets.")

        # Default changes
        if db.query(ChangeRecord).count() == 0:
            chg = ChangeRecord(
                id="chg-patch", title="Patch production database servers",
                description="Apply security patch KB-2024-06 to all production DB servers. Requires 30-minute maintenance window.",
                change_type="Standard", status="CAB Review", priority="P1", risk_level="Medium",
                impact="Production databases will be unavailable for 10-15 minutes during failover.",
                rollback_plan="Fail back to standby node if patch fails.", test_plan="Tested in staging environment — zero issues.",
                scheduled_start=datetime.utcnow() + timedelta(days=3, hours=2),
                scheduled_end=datetime.utcnow() + timedelta(days=3, hours=3),
                requested_by="u-carol", assigned_to="u-alice",
            )
            db.add(chg)
            db.flush()
            db.add(ChangeApprovalRecord(change_id="chg-patch", approver_id="u-carol", decision="approved", decided_at=datetime.utcnow()))
            db.add(ChangeApprovalRecord(change_id="chg-patch", approver_id="u-bob"))
            db.commit()
            print("Seed: inserted 1 change with 2 approvals.")

        # Default assets
        if db.query(AssetRecord).count() == 0:
            for ast in [
                {"id": "ast-mbp1", "name": "MacBook Pro 16 M3", "asset_type": "Hardware", "asset_tag": "MAC-0042", "status": "In Use", "owner_id": "u-alice", "location": "HQ Floor 2", "vendor": "Apple", "model": "MBP16-M3-2024", "purchase_date": datetime.utcnow() - timedelta(days=180), "warranty_expiry": datetime.utcnow() + timedelta(days=550), "cost": 2499.00},
                {"id": "ast-tp1", "name": "ThinkPad X1 Carbon Gen 11", "asset_type": "Hardware", "asset_tag": "TP-0117", "status": "In Use", "owner_id": "u-bob", "location": "HQ Floor 3", "vendor": "Lenovo", "model": "X1C-G11", "purchase_date": datetime.utcnow() - timedelta(days=300), "warranty_expiry": datetime.utcnow() + timedelta(days=430), "cost": 1899.00},
                {"id": "ast-mon1", "name": "Dell UltraSharp U2723QE", "asset_type": "Hardware", "asset_tag": "MON-0089", "status": "Available", "location": "Storage Room B", "vendor": "Dell", "model": "U2723QE", "purchase_date": datetime.utcnow() - timedelta(days=90), "cost": 549.00},
                {"id": "ast-ms365", "name": "Microsoft 365 E5 License", "asset_type": "License", "asset_tag": "LIC-0152", "status": "In Use", "vendor": "Microsoft", "purchase_date": datetime.utcnow() - timedelta(days=365), "warranty_expiry": datetime.utcnow() + timedelta(days=365), "cost": 684.00, "notes": "Annual renewal"},
                {"id": "ast-sw1", "name": "Cisco Catalyst 9300 Switch", "asset_type": "Network", "asset_tag": "SW-0041", "status": "In Use", "location": "Server Rack A-12", "vendor": "Cisco", "model": "C9300-48P", "purchase_date": datetime.utcnow() - timedelta(days=500), "warranty_expiry": datetime.utcnow() + timedelta(days=230), "cost": 4295.00},
                {"id": "ast-srv1", "name": "Dell PowerEdge R750", "asset_type": "Hardware", "asset_tag": "SRV-0023", "status": "In Use", "location": "Data Center Rack C-04", "vendor": "Dell", "model": "R750", "purchase_date": datetime.utcnow() - timedelta(days=200), "warranty_expiry": datetime.utcnow() + timedelta(days=530), "cost": 12500.00},
            ]:
                db.add(AssetRecord(**ast))
            db.commit()
            print("Seed: inserted 5 assets.")

        # Default survey templates
        if db.query(SurveyTemplateRecord).count() == 0:
            for tmpl in [
                {"name": "Standard CSAT", "question": "How satisfied were you with the resolution of your issue?"},
                {"name": "Quick Rating", "question": "On a scale of 1-5, how would you rate your support experience?"},
                {"name": "Detailed Feedback", "question": "Please rate the quality of support you received and share any additional feedback."},
            ]:
                db.add(SurveyTemplateRecord(**tmpl))
            db.commit()
            print("Seed: inserted 3 survey templates.")

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