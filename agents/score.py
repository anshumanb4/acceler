#!/usr/bin/env python3
"""Priority scoring agent: score enriched people based on connection proximity, relevance, and urgency."""

import argparse
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, List

import anthropic
from config import supabase, ANTHROPIC_API_KEY, CLAUDE_MODEL, CLAUDE_MAX_TOKENS

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# Re-score if older than this
SCORE_STALE_DAYS = 7

PROFILE_PATH = "profile.yaml"

SCORE_PROMPT = """You are scoring a business development prospect for priority outreach. You will return a JSON object with scores and reasons.

## Anshuman Bapna's Background
{profile_text}

## What the outreach tags mean
- **acceler**: BD for Acceler — targets CIOs, CTOs, and digital transformation leaders at large enterprises
- **terra**: BD for Terra.do — targets sustainability/ESG/climate leaders, CSOs, and companies investing in climate action

## Person to Score
Name: {name}
Title: {title}
Organization: {organization}
Tag: {for_tag}
Seniority: {seniority}
Org Industry: {org_industry}
Org Employee Count: {org_employee_count}
Org Revenue: {org_revenue}
Org Total Funding: {org_total_funding}
Context: {context}
Employment History: {employment_history}
Is 1st-degree LinkedIn connection: {is_first_degree}

## Scoring Rubric

### 1. Connection Proximity (0-30 points)
How close is Anshuman to this person based on shared background?
- 1st-degree LinkedIn connection: 30 pts
- Shared company (both worked there, even at different times): 20 pts
- Shared alma mater (Stanford GSB, IIT Bombay): 15 pts
- Shared industry experience (travel, climate, consulting, finserv, etc.): 10 pts
- Same region (Bay Area, Bangalore/India, New York): 5 pts
- Fellow CXO / fellow founder / fellow NASDAQ executive: 5 pts
- These stack but cap at 30 total

### 2. Relevance (0-40 points)
How relevant is this person for outreach given their tag (acceler vs terra)?
- Seniority: C-suite 15, VP 10, Director 7, Manager 3, other 1
- Org scale: >$1B rev/funding 10, >$100M 7, >$10M 4, smaller/unknown 1
- Role-tag fit: How well does their title/role match what acceler or terra targets? 0-15 pts
  - For acceler: CIO, CTO, CDO, Head of Digital, VP Engineering = high fit
  - For terra: CSO (sustainability), Head of ESG, VP Sustainability, Climate Officer = high fit

### 3. Urgency (0-30 points)
Is there a time-sensitive reason to reach out now?
- Speaking at upcoming event (next 30 days from today {today}): 25-30 pts
- Speaking at recent event (last 60 days): 15-20 pts
- Event is well-known / prestigious: +5 pts
- Quoted/published recently giving specific topical hook: 10 pts
- Recently changed roles (from employment history): 10 pts
- Event already past (>60 days ago): 3-5 pts
- No time-sensitive signal: 0 pts

## Output Format
Return ONLY valid JSON, no other text:
{{
  "proximity_score": <0-30>,
  "proximity_reasons": "<brief explanation of shared connections found>",
  "relevance_score": <0-40>,
  "relevance_reasons": "<brief explanation>",
  "urgency_score": <0-30>,
  "urgency_reasons": "<brief explanation>",
  "total_score": <sum of above, 0-100>,
  "summary": "<one line, max 120 chars, combining the top reasons — this shows in a dashboard column>"
}}"""


def load_profile() -> str:
    """Load profile.yaml as raw text for the prompt."""
    with open(PROFILE_PATH, "r") as f:
        return f.read()


def get_employment_history(apollo_data) -> str:
    """Extract employment history from apollo_data for the prompt."""
    if not apollo_data:
        return "Not available"
    raw = json.loads(apollo_data) if isinstance(apollo_data, str) else apollo_data
    history = raw.get("employment_history", [])
    if not history:
        return "Not available"
    lines = []
    for h in history[:10]:  # cap at 10
        org = h.get("organization_name", "")
        title = h.get("title", "")
        start = h.get("start_date", "")
        end = h.get("end_date", "present" if h.get("current") else "")
        lines.append(f"- {title} at {org} ({start} to {end})")
    return "\n".join(lines)


def score_person(person: dict, profile_text: str, today: str) -> dict:
    """Score a single person using Claude. Returns score dict."""
    context = person.get("context") or ""
    is_first_degree = "[1st-degree LinkedIn connection]" in context

    prompt = SCORE_PROMPT.format(
        profile_text=profile_text,
        name=person["name"],
        title=person.get("title") or "",
        organization=person.get("organization") or "",
        for_tag=person.get("for_tag") or "",
        seniority=person.get("seniority") or "",
        org_industry=person.get("org_industry") or "",
        org_employee_count=person.get("org_employee_count") or "Unknown",
        org_revenue=person.get("org_revenue") or "Unknown",
        org_total_funding=person.get("org_total_funding") or "Unknown",
        context=context,
        employment_history=get_employment_history(person.get("apollo_data")),
        is_first_degree="Yes" if is_first_degree else "No",
        today=today,
    )

    for attempt in range(3):
        try:
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            break
        except anthropic.RateLimitError:
            wait = 2 ** attempt * 5
            print(f"  Rate limited, waiting {wait}s...")
            time.sleep(wait)
    else:
        raise RuntimeError("Claude API rate limit exceeded after 3 retries")

    text = response.content[0].text.strip()
    # Strip code fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else text[3:]
    text = text.rstrip("`").strip()

    return json.loads(text)


def get_people_to_score(person_id: Optional[str] = None, for_tag: Optional[str] = None, force: bool = False) -> List[dict]:
    """Fetch people to score from Supabase."""
    query = supabase.table("people").select("*")
    if person_id:
        query = query.eq("id", person_id)
    else:
        query = query.eq("status", "enriched")
        if for_tag:
            query = query.eq("for_tag", for_tag)
    result = query.execute()

    if force:
        return result.data

    # Filter out recently scored
    cutoff = (datetime.now(timezone.utc) - timedelta(days=SCORE_STALE_DAYS)).isoformat()
    return [p for p in result.data if not p.get("scored_at") or p["scored_at"] < cutoff]


def main():
    parser = argparse.ArgumentParser(description="Priority scoring agent: score enriched people")
    parser.add_argument("--person-id", help="Score a single person by UUID")
    parser.add_argument("--for-tag", help="Only score people with this tag")
    parser.add_argument("--dry-run", action="store_true", help="Preview without DB writes")
    parser.add_argument("--force", action="store_true", help="Re-score even if recently scored")
    args = parser.parse_args()

    profile_text = load_profile()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    people = get_people_to_score(args.person_id, args.for_tag, args.force)
    if not people:
        print("No people to score (all recently scored or none enriched).")
        return

    print(f"Scoring {len(people)} person(s)...")

    scored = 0
    errors = 0
    for i, person in enumerate(people):
        print(f"\n--- [{i+1}/{len(people)}] {person['name']} | {person.get('organization', '')}")
        try:
            result = score_person(person, profile_text, today)
            total = result["total_score"]
            summary = result.get("summary", "")
            shared = result.get("proximity_reasons", "")

            print(f"  Score: {total}/100 — {summary}")
            print(f"    Proximity: {result['proximity_score']}/30 | Relevance: {result['relevance_score']}/40 | Urgency: {result['urgency_score']}/30")

            if not args.dry_run:
                # Build reasons text with breakdown
                reasons = (
                    f"[{result['proximity_score']}/{result['relevance_score']}/{result['urgency_score']}] "
                    f"{summary}"
                )
                supabase.table("people").update({
                    "priority_score": total,
                    "priority_reasons": reasons,
                    "shared_background": shared,
                    "scored_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", person["id"]).execute()

            scored += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            errors += 1

        # Small delay to avoid Claude rate limits
        if i < len(people) - 1:
            time.sleep(0.5)

    print(f"\n=== Summary ===")
    print(f"People scored:  {scored}")
    print(f"Errors:         {errors}")

    if errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
