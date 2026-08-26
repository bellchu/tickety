import os
import secrets
import hashlib
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .database import (
    SessionLocal, TicketRecord, UserRecord, RecognitionRecord,
    ExternalUserRecord, SyncStateRecord, TicketCategoryRecord,
    KbArticleRecord, TicketStatusConfigRecord, TicketPriorityConfigRecord,
    NotificationConfigRecord,
    ProjectRecord, ServiceItemRecord, ServiceRequestRecord,
    ProblemRecord, ProblemTicketLinkRecord,
    ChangeRecord, ChangeApprovalRecord,
    AssetRecord, SurveyTemplateRecord,
)

PASSWORD_HASH_ITERATIONS = 390_000


def _hash_pw(pw: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        pw.encode("utf-8"),
        salt.encode("ascii"),
        PASSWORD_HASH_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${PASSWORD_HASH_ITERATIONS}${salt}${digest}"

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

EXTERNAL_USERS = [
    {"id": "ext-demo-1001", "external_id": "1001", "name": "Morgan Lee", "email": "morgan@provider.example"},
    {"id": "ext-demo-1002", "external_id": "1002", "name": "Riley Patel", "email": "riley@provider.example"},
    {"id": "ext-demo-1003", "external_id": "1003", "name": "Jordan Kim", "email": "jordan@provider.example"},
]

SEED_NOW = datetime.utcnow()


def _ago(days: int, hours: int = 0) -> datetime:
    return SEED_NOW - timedelta(days=days, hours=hours)


def _ahead(days: int, hours: int = 0) -> datetime:
    return SEED_NOW + timedelta(days=days, hours=hours)


def _seed_ticket(
    n: int,
    subject: str,
    description: str,
    reporter: str,
    priority: str,
    status: str,
    category: str,
    ticket_type: str,
    created_days_ago: int,
    assignee: str,
    sentiment: str = "Neutral",
    mood: str = "neutral",
    complexity: int = 2,
    resolved_by: str | None = None,
    resolution_days_after: int | None = None,
    points: int = 0,
    impact: str | None = None,
    urgency: str | None = None,
    tags: str | None = None,
) -> dict:
    created_at = _ago(created_days_ago)
    resolved_at = (
        created_at + timedelta(days=resolution_days_after)
        if resolution_days_after is not None
        else None
    )
    updated_at = resolved_at or min(created_at + timedelta(days=max(1, created_days_ago // 8)), SEED_NOW)
    reasoning_action = "escalate" if status == "Escalated" or priority == "P1" else "route" if ticket_type == "request" else "respond"
    return {
        "id": f"t-{n:03d}",
        "external_id": str(100 + n),
        "subject": subject,
        "description": description,
        "reporter": reporter,
        "priority": priority,
        "status": status,
        "workflow_status": status,
        "external_status": "Pending" if status == "Awaiting Review" else status,
        "external_assignee_id": assignee,
        "ticket_type": ticket_type,
        "impact": impact,
        "urgency": urgency,
        "tags": tags or category.lower().replace(" ", "-"),
        "sentiment": sentiment,
        "mood": mood,
        "category": category,
        "complexity": complexity,
        "created_at": created_at,
        "updated_at": updated_at,
        "external_created_at": created_at,
        "external_updated_at": updated_at,
        "due_by": created_at + timedelta(hours={"P1": 4, "P2": 24, "P3": 72}.get(priority, 168)),
        "fr_due_by": created_at + timedelta(hours=4 if priority in {"P1", "P2"} else 12),
        "resolved_by": resolved_by,
        "resolved_at": resolved_at,
        "external_resolved_at": resolved_at,
        "points_awarded": points,
        "ai_reasoning": (
            f"sentiment: {sentiment}, category: {category}, priority: {priority}, "
            f"mood: {mood}, action: {reasoning_action} | Reasoning: {ticket_type.title()} scenario for {category.lower()} operations and analytics."
        ),
    }


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

TICKETS.extend([
    _seed_ticket(16, "Suspicious inbox forwarding rule detected", "Security monitoring found an auto-forwarding rule sending finance mail to an external address.", "secops@company.com", "P1", "Escalated", "Security", "incident", 180, "1001", "Business-Critical", "critical", 5, "u-alice", 2, 50, "Enterprise", "Critical", "security,email,possible-compromise"),
    _seed_ticket(17, "Request: temporary VPN access for contractor", "Please grant VPN access for a contractor supporting the payroll migration for two weeks.", "hr-ops@company.com", "P2", "Closed", "Access Request", "request", 174, "1002", "Neutral", "neutral", 2, "u-bob", 3, 30, "Department", "High", "vpn,contractor,access"),
    _seed_ticket(18, "Quarter-end report export timing out", "The finance reporting export times out after 12 minutes and never downloads the CSV.", "finance@company.com", "P2", "Closed", "Data", "incident", 169, "1003", "High-Impact", "urgent", 4, "u-carol", 4, 30, "Department", "High", "finance,reporting,data-export"),
    _seed_ticket(19, "Change request: firewall rule for vendor SFTP", "Need an approved firewall rule allowing outbound SFTP to the benefits provider.", "infra@company.com", "P3", "Awaiting Review", "Network", "request", 163, "1001", "Neutral", "neutral", 3, None, None, 0, "Team", "Medium", "change,firewall,vendor"),
    _seed_ticket(20, "Conference room display will not wake", "Room 4B display stays black even after power cycling the controller.", "facilities@company.com", "P3", "Closed", "Facilities", "incident", 158, "1002", "Neutral", "neutral", 2, "u-bob", 1, 15, "Office", "Medium", "av,conference-room,hardware"),
    _seed_ticket(21, "New service account for warehouse scanner API", "Create a non-human account and token rotation policy for the scanner integration.", "warehouse@company.com", "P3", "Closed", "Identity", "request", 152, "1003", "Neutral", "neutral", 2, "u-carol", 5, 15, "Team", "Medium", "service-account,api,identity"),
    _seed_ticket(22, "AWS monthly cost anomaly in analytics workspace", "Analytics workspace spend is 42% higher than baseline after a cluster resize.", "data-eng@company.com", "P2", "Open", "Cloud", "incident", 146, "1001", "High-Impact", "concerned", 4, None, None, 0, "Department", "High", "aws,cost,analytics"),
    _seed_ticket(23, "Request: enroll team in password manager", "Please add the growth team to the password manager and assign the marketing vault.", "growth@company.com", "P4", "Closed", "Access Request", "request", 140, "1002", "Positive", "satisfied", 1, "u-bob", 2, 15, "Team", "Low", "password-manager,onboarding"),
    _seed_ticket(24, "Customer portal form creates duplicate tickets", "Submitting the public support form sometimes creates two tickets with the same request ID.", "support-ops@company.com", "P2", "Escalated", "Software", "incident", 134, "1003", "High-Impact", "urgent", 4, None, None, 0, "Customer", "High", "portal,deduplication,bug"),
    _seed_ticket(25, "Request: replace expired SSL certificate", "The staging API certificate expires this week and needs replacement before QA testing.", "qa@company.com", "P2", "Closed", "Security", "request", 128, "1001", "Neutral", "concerned", 3, "u-alice", 1, 30, "Service", "High", "ssl,certificate,staging"),
    _seed_ticket(26, "Mobile device lost on business trip", "An employee lost an enrolled phone while traveling and needs remote wipe confirmation.", "travel@company.com", "P1", "Closed", "Mobile", "incident", 122, "1002", "Business-Critical", "urgent", 4, "u-bob", 1, 50, "User", "Critical", "mobile,mdm,remote-wipe"),
    _seed_ticket(27, "Request: Jira project for AI sidekick pilot", "Create a Jira project with issue types and permissions for the AI sidekick pilot team.", "pilot@company.com", "P3", "Closed", "Software", "request", 116, "1003", "Positive", "satisfied", 2, "u-carol", 2, 15, "Team", "Medium", "jira,pilot,project"),
    _seed_ticket(28, "Payroll app SSO redirect loop", "Payroll users are bounced between the app and identity provider after login.", "payroll@company.com", "P1", "Escalated", "Identity", "incident", 110, "1001", "Business-Critical", "critical", 5, None, None, 0, "Enterprise", "Critical", "sso,payroll,identity"),
    _seed_ticket(29, "Request: add shared mailbox delegates", "Add three assistants as delegates on the executive support shared mailbox.", "exec-ops@company.com", "P3", "Closed", "Email", "request", 104, "1002", "Neutral", "neutral", 1, "u-bob", 1, 15, "Team", "Medium", "shared-mailbox,delegates"),
    _seed_ticket(30, "Warehouse label printer calibration drift", "Shipping labels print 4 mm too low and barcodes fail scanning at pack stations.", "warehouse@company.com", "P2", "Open", "Hardware", "incident", 98, "1003", "High-Impact", "urgent", 3, None, None, 0, "Site", "High", "printer,warehouse,barcode"),
    _seed_ticket(31, "Change request: database maintenance window", "Schedule a maintenance window to rebuild indexes on the customer analytics database.", "dba@company.com", "P3", "Awaiting Review", "Database", "request", 92, "1001", "Neutral", "neutral", 3, None, None, 0, "Service", "Medium", "change,database,maintenance"),
    _seed_ticket(32, "Teams calls drop when screen sharing", "Video calls disconnect after screen sharing starts on the latest desktop client.", "sales@company.com", "P2", "Closed", "Collaboration", "incident", 86, "1002", "Moderate", "concerned", 3, "u-bob", 4, 30, "Department", "High", "teams,screen-sharing,collaboration"),
    _seed_ticket(33, "Request: loaner laptop for visiting auditor", "A visiting auditor needs a managed loaner laptop with restricted network access.", "audit@company.com", "P3", "Closed", "Hardware", "request", 80, "1003", "Neutral", "neutral", 2, "u-carol", 2, 15, "User", "Medium", "loaner,audit,laptop"),
    _seed_ticket(34, "EDR agent consuming high CPU", "Several engineering workstations report sustained CPU over 90% from the endpoint agent.", "engineering@company.com", "P2", "Escalated", "Security", "incident", 74, "1001", "High-Impact", "urgent", 4, None, None, 0, "Department", "High", "edr,cpu,endpoint"),
    _seed_ticket(35, "Request: update DNS record for campaign site", "Marketing needs the campaign CNAME updated before the launch announcement.", "marketing@company.com", "P3", "Closed", "Network", "request", 68, "1002", "Positive", "neutral", 2, "u-bob", 1, 15, "Service", "Medium", "dns,campaign,marketing"),
    _seed_ticket(36, "Inventory sync job failed overnight", "Asset inventory stopped syncing from procurement and new laptops are missing from CMDB.", "procurement@company.com", "P3", "Open", "Assets", "incident", 62, "1003", "Moderate", "concerned", 3, None, None, 0, "Team", "Medium", "assets,cmdb,sync"),
    _seed_ticket(37, "Request: Okta group for finance analysts", "Create an Okta group for finance analysts and map it to BI dashboard permissions.", "finance@company.com", "P3", "Closed", "Identity", "request", 56, "1001", "Neutral", "neutral", 2, "u-alice", 2, 15, "Department", "Medium", "okta,group,bi"),
    _seed_ticket(38, "Point-of-sale tablet battery swelling", "A store tablet has a visibly swollen battery and should be replaced urgently.", "store-12@company.com", "P1", "Closed", "Hardware", "incident", 50, "1002", "Business-Critical", "urgent", 4, "u-bob", 1, 50, "Site", "Critical", "pos,tablet,battery"),
    _seed_ticket(39, "Request: publish knowledge article for VPN split tunnel", "Document how to use split tunneling for trusted SaaS traffic during travel.", "networking@company.com", "P4", "Closed", "Knowledge", "request", 46, "1003", "Positive", "satisfied", 1, "u-carol", 3, 15, "Team", "Low", "kb,vpn,documentation"),
    _seed_ticket(40, "Data warehouse load delayed after schema change", "Nightly data warehouse load failed after a source table renamed two columns.", "analytics@company.com", "P2", "Open", "Data", "incident", 42, "1001", "High-Impact", "urgent", 4, None, None, 0, "Department", "High", "data-warehouse,etl,schema"),
    _seed_ticket(41, "Request: emergency access review export", "Compliance needs a CSV export of emergency access grants for the last quarter.", "compliance@company.com", "P3", "Awaiting Review", "Security", "request", 38, "1002", "Neutral", "concerned", 3, None, None, 0, "Enterprise", "Medium", "compliance,access-review,export"),
    _seed_ticket(42, "MacOS update broke smart card login", "After the latest macOS patch, smart card login fails for legal team laptops.", "legal@company.com", "P2", "Escalated", "Endpoint", "incident", 34, "1003", "High-Impact", "urgent", 4, None, None, 0, "Department", "High", "macos,smart-card,endpoint"),
    _seed_ticket(43, "Request: deprovision departing employee", "Remove app access, disable accounts, and preserve mailbox for a departing employee.", "hr@company.com", "P2", "Closed", "Access Request", "request", 30, "1001", "Neutral", "neutral", 2, "u-alice", 1, 30, "User", "High", "offboarding,deprovision,mailbox"),
    _seed_ticket(44, "Guest Wi-Fi captive portal certificate warning", "Visitors see a browser warning when joining guest Wi-Fi in the lobby.", "reception@company.com", "P3", "Open", "Network", "incident", 27, "1002", "Moderate", "concerned", 2, None, None, 0, "Office", "Medium", "guest-wifi,certificate"),
    _seed_ticket(45, "Request: provision new hire SaaS bundle", "Provision email, Slack, HRIS, payroll, and project management access for a new hire.", "peopleops@company.com", "P2", "Closed", "Access Request", "request", 24, "1003", "Positive", "satisfied", 2, "u-carol", 1, 30, "User", "High", "onboarding,saas,new-hire"),
    _seed_ticket(46, "Backup verification failed for file server", "The weekly restore verification failed for the department file server backup.", "backup@company.com", "P2", "Escalated", "Infrastructure", "incident", 21, "1001", "High-Impact", "urgent", 4, None, None, 0, "Service", "High", "backup,restore,file-server"),
    _seed_ticket(47, "Request: add procurement approval workflow", "Configure an approval workflow for purchases over the new department threshold.", "procurement@company.com", "P4", "Awaiting Review", "Workflow", "request", 18, "1002", "Neutral", "neutral", 2, None, None, 0, "Department", "Low", "workflow,approval,procurement"),
    _seed_ticket(48, "CRM webhook backlog causing stale customer updates", "CRM integration webhook queue is delayed by 90 minutes and customer updates are stale.", "customer-success@company.com", "P2", "Open", "Integration", "incident", 15, "1003", "High-Impact", "urgent", 4, None, None, 0, "Customer", "High", "crm,webhook,integration"),
    _seed_ticket(49, "Request: new dashboard viewer role", "Create a read-only dashboard role for regional managers.", "ops@company.com", "P3", "Closed", "Access Request", "request", 12, "1001", "Positive", "neutral", 1, "u-alice", 1, 15, "Department", "Medium", "dashboard,role,read-only"),
    _seed_ticket(50, "VPN MFA push fatigue reported by executive", "An executive received repeated unexpected MFA pushes while trying to connect to VPN.", "executive-support@company.com", "P1", "Escalated", "Security", "incident", 10, "1002", "Business-Critical", "critical", 5, None, None, 0, "User", "Critical", "mfa,vpn,security"),
    _seed_ticket(51, "Request: archive inactive Slack channels", "Archive stale project channels and export message history for records retention.", "records@company.com", "P4", "Closed", "Collaboration", "request", 8, "1003", "Neutral", "neutral", 1, "u-carol", 2, 15, "Team", "Low", "slack,archive,retention"),
    _seed_ticket(52, "Billing system PDF invoices render blank", "Generated customer invoice PDFs are blank when downloaded from the billing system.", "billing@company.com", "P2", "Open", "Software", "incident", 7, "1001", "High-Impact", "urgent", 3, None, None, 0, "Customer", "High", "billing,pdf,invoices"),
    _seed_ticket(53, "Request: emergency patch deployment approval", "Approve expedited deployment for a critical browser vulnerability patch.", "endpoint@company.com", "P1", "Awaiting Review", "Change", "request", 5, "1002", "Business-Critical", "urgent", 4, None, None, 0, "Enterprise", "Critical", "change,patch,security"),
    _seed_ticket(54, "Warehouse handheld scanner cannot join Wi-Fi", "New handheld scanner model cannot authenticate to the warehouse wireless network.", "warehouse@company.com", "P2", "Open", "Network", "incident", 4, "1003", "Moderate", "concerned", 3, None, None, 0, "Site", "High", "scanner,wifi,warehouse"),
    _seed_ticket(55, "Request: increase mailbox retention for legal hold", "Extend retention for a set of mailboxes related to a legal hold request.", "legal@company.com", "P2", "Awaiting Review", "Email", "request", 3, "1001", "Neutral", "concerned", 3, None, None, 0, "Department", "High", "mailbox,retention,legal-hold"),
    _seed_ticket(56, "Kubernetes dev namespace image pull failures", "Developers cannot deploy to the sandbox namespace because image pulls fail with auth errors.", "platform@company.com", "P2", "Open", "Cloud", "incident", 2, "1002", "Moderate", "concerned", 3, None, None, 0, "Team", "High", "kubernetes,registry,dev"),
    _seed_ticket(57, "Request: issue YubiKeys for finance team", "Finance team needs hardware security keys before the privileged access rollout.", "finance@company.com", "P3", "Open", "Security", "request", 2, "1003", "Positive", "neutral", 2, None, None, 0, "Department", "Medium", "yubikey,mfa,finance"),
    _seed_ticket(58, "Customer support macros disappeared", "Support agents no longer see saved response macros in the helpdesk sidebar.", "support@company.com", "P2", "Escalated", "Software", "incident", 1, "1001", "High-Impact", "urgent", 3, None, None, 0, "Customer", "High", "support,macros,helpdesk"),
    _seed_ticket(59, "Request: guest account for onsite vendor", "Create a guest account with building Wi-Fi and limited SharePoint access for onsite vendor.", "facilities@company.com", "P3", "New", "Access Request", "request", 1, "1002", "Neutral", "neutral", 1, None, None, 0, "User", "Medium", "guest,vendor,sharepoint"),
    _seed_ticket(60, "Monitoring alert: API latency above SLO", "Public API p95 latency has exceeded the SLO for the last 20 minutes.", "sre@company.com", "P1", "Open", "Infrastructure", "incident", 0, "1003", "Business-Critical", "critical", 5, None, None, 0, "Customer", "Critical", "slo,latency,api"),
])

for index, ticket in enumerate(TICKETS, start=1):
    ticket.setdefault("ticket_type", "request" if ticket["subject"].lower().startswith(("request:", "how do i", "new ")) or "access" in ticket["subject"].lower() else "incident")
    ticket.setdefault("impact", "Enterprise" if ticket["priority"] == "P1" else "Department" if ticket["priority"] == "P2" else "Team")
    ticket.setdefault("urgency", "Critical" if ticket["priority"] == "P1" else "High" if ticket["priority"] == "P2" else "Medium" if ticket["priority"] == "P3" else "Low")
    ticket.setdefault("tags", ",".join(filter(None, [ticket.get("category", "").lower().replace(" ", "-"), ticket.get("ticket_type")])))
    ticket.setdefault("created_at", _ago(min(180, 3 + index * 4), index % 7))
    ticket.setdefault("updated_at", ticket.get("resolved_at") or min(ticket["created_at"] + timedelta(days=max(1, index % 9)), SEED_NOW))
    ticket.setdefault("external_created_at", ticket["created_at"])
    ticket.setdefault("external_updated_at", ticket["updated_at"])
    ticket.setdefault("workflow_status", ticket["status"])
    ticket.setdefault("due_by", ticket["created_at"] + timedelta(hours={"P1": 4, "P2": 24, "P3": 72}.get(ticket["priority"], 168)))
    ticket.setdefault("fr_due_by", ticket["created_at"] + timedelta(hours=4 if ticket["priority"] in {"P1", "P2"} else 12))

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
        db.query(ExternalUserRecord).delete()
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

        # Provider-owned demo directory. These records intentionally have no
        # relationship to the Tickety users above.
        for external_user in EXTERNAL_USERS:
            db.add(ExternalUserRecord(
                id=external_user["id"],
                binding_id="legacy",
                provider="standalone",
                external_id=external_user["external_id"],
                user_type="agent",
                name=external_user["name"],
                email=external_user["email"],
                active=True,
                profile_json="{}",
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
                ticket_type=t.get("ticket_type", "incident"),
                impact=t.get("impact"),
                urgency=t.get("urgency"),
                workflow_status=t.get("workflow_status", t["status"]),
                ai_review_state=t.get("ai_review_state"),
                due_by=t.get("due_by"),
                response_due_at=t.get("fr_due_by"),
                resolution_due_at=t.get("due_by"),
                tags=t.get("tags"),
                external_source="standalone",
                external_id=t["external_id"],
                external_url=url,
                external_status=t.get("external_status"),
                external_assignee_id=t.get("external_assignee_id"),
                external_created_at=t.get("external_created_at"),
                external_updated_at=t.get("external_updated_at"),
                external_resolved_at=t.get("external_resolved_at"),
                external_due_by=t.get("due_by"),
                external_fr_due_by=t.get("fr_due_by"),
                resolved_by=t.get("resolved_by"),
                resolved_at=t.get("resolved_at"),
                points_awarded=t.get("points_awarded", 0),
                points_awarded_sent=True,
                created_at=t.get("created_at"),
                updated_at=t.get("updated_at"),
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
                {"name": "Security", "description": "Security events, vulnerabilities, and access risk", "color": "red"},
                {"name": "Cloud", "description": "Cloud infrastructure, Kubernetes, and SaaS platform issues", "color": "blue"},
                {"name": "Identity", "description": "SSO, MFA, identity provider, and account lifecycle work", "color": "violet"},
                {"name": "Data", "description": "Reporting, warehouse, analytics, and data pipeline issues", "color": "emerald"},
                {"name": "Collaboration", "description": "Chat, meetings, shared workspaces, and team productivity tools", "color": "cyan"},
                {"name": "Infrastructure", "description": "Servers, backups, monitoring, and platform reliability", "color": "amber"},
                {"name": "Facilities", "description": "Office technology and workplace equipment", "color": "slate"},
                {"name": "Mobile", "description": "Mobile devices, MDM, and handheld equipment", "color": "blue"},
                {"name": "Database", "description": "Database maintenance, performance, and availability", "color": "emerald"},
                {"name": "Assets", "description": "CMDB, inventory, procurement, and asset lifecycle", "color": "amber"},
                {"name": "Knowledge", "description": "Knowledge base and documentation requests", "color": "slate"},
                {"name": "Endpoint", "description": "Desktop OS, device agents, and endpoint authentication", "color": "blue"},
                {"name": "Workflow", "description": "Approval flows and business process automation", "color": "violet"},
                {"name": "Integration", "description": "API, webhook, and system-to-system integration issues", "color": "cyan"},
                {"name": "Change", "description": "Change enablement and deployment approval work", "color": "amber"},
                {"name": "Other", "description": "Miscellaneous issues", "color": "slate"},
            ]:
                db.add(TicketCategoryRecord(**cat))
            db.commit()
            print("Seed: inserted default ticket categories.")

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
                status="Under Investigation", priority="P1", category="Network",
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
        print(f"Seed error kind={type(e).__name__}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run_seed()
