Triage_PROMPT = """
Analyze the following IT support ticket and return a JSON object.
The ticket details:
Subject: {subject}
Description: {description}

Return exactly this JSON structure:
{{
  "sentiment": "Business-Critical | High-Impact | Moderate | Neutral | Positive",
  "category": "Hardware | Software | Network | Access Request | Other",
  "priority": "P1 | P2 | P3",
  "mood": "critical | urgent | concerned | neutral | satisfied",
  "action": "escalate | respond | route",
  "reasoning": "A brief explanation of why you chose these values"
}}

The "sentiment" and "mood" fields are companion measures of how much this
ticket matters to the BUSINESS, not just polarity. Pick them together:

"sentiment" = business blast radius (how WIDE the impact is), NOT the single
person's emotional intensity (that's `mood`).
  - Business-Critical: business operations are DOWN; revenue, SLA, or
    reputation at risk; or a whole team / customer-facing service is affected.
  - High-Impact:       significant disruption AND the impact is SPREADING
    beyond one person (a team, a shared service, or escalating outward).
  - Moderate:          real but CONTAINED impact on productivity.
  - Neutral:           calm, routine request, no meaningful business impact.
  - Positive:          satisfied/appreciative; no negative impact.

HARD RULE on scope (apply BEFORE choosing sentiment):
  - If the impact is confined to a SINGLE user and is NOT spreading, the
    sentiment is AT MOST "Moderate" — never High-Impact or Business-Critical,
    no matter how frustrated that one user sounds. Intensity goes into `mood`.
  - Only escalate past Moderate when the blast radius genuinely widens
    (multiple users, a shared/team service, or a customer-facing outage).

"mood" = how time-critical the customer feels (one person's intensity):
  - critical:   business-down / blocking work; furious or panicked.
  - urgent:     frustrated and time-pressured; tempers rising.
  - concerned:  worried about a deadline or potential impact, not yet angry.
  - neutral:    matter-of-fact, routine.
  - satisfied:  happy, appreciative, low-stakes.

Weight business blast radius (how many people/systems are affected) higher
than how loudly one person complains. "sentiment" measures spread of impact;
"mood" measures that one person's emotional intensity. They CAN differ: a
single user may be `mood: urgent` while `sentiment` stays `Moderate`.
"sentiment" and "mood" should usually align (e.g. Business-Critical ↔
critical), but can differ when urgency and impact diverge. When unsure of the
blast radius, default to the SMALLER scope.

The "reasoning" MUST start with the affected scope, e.g.
"scope: single user" / "scope: team" / "scope: customer-facing service",
then justify the sentiment and mood in one sentence.
"""

REPLY_PROMPT = """
Based on the ticket and the provided knowledge base info, draft a professional, helpful response to the user.
Ticket: {subject} - {description}
Knowledge Base: {kb_info}

Return exactly this JSON structure:
{{
  "suggested_response": "Your drafted text here"
}}
"""

RECOGNITIONS = {
    "first_resolution": {
        "display_name": "First Resolution",
        "description": "Resolved your first ticket",
        "icon": "medal",
    },
    "consistent_performer": {
        "display_name": "Consistent Performer",
        "description": "Maintained 10-ticket processing momentum",
        "icon": "flame",
    },
    "critical_specialist": {
        "display_name": "Critical Issue Specialist",
        "description": "Resolved 5 P1 tickets",
        "icon": "alert-octagon",
    },
    "rapid_responder": {
        "display_name": "Rapid Responder",
        "description": "Resolved a ticket within 5 minutes",
        "icon": "zap",
    },
    "sentiment_expert": {
        "display_name": "Sentiment Expert",
        "description": "Correctly identified customer sentiment 10 times",
        "icon": "heart",
    },
    "reliability_streak": {
        "display_name": "Reliability Streak",
        "description": "Active contribution for 7 consecutive days",
        "icon": "calendar-check",
    },
}

TIER_THRESHOLDS = [0, 100, 250, 500, 1000, 2000, 4000, 8000]

PRIORITY_POINTS = {"P1": 50, "P2": 30, "P3": 15}
MOMENTUM_BONUS_CAP = 2.0
MOMENTUM_RESET_HOURS = 24