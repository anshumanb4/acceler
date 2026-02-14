#!/usr/bin/env python3
"""Research-enhanced email drafting agent: web research + personalized draft for a single person."""

import argparse
import json
import os
import sys
import time
from typing import Optional

import anthropic
from config import supabase, ANTHROPIC_API_KEY, CLAUDE_MODEL, CLAUDE_MAX_TOKENS

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

PROFILE_PATH = "profile.yaml"
TEMPLATES_DIR = "templates"
EMAIL_SKILLS_PATH = os.path.join(TEMPLATES_DIR, "email_skills.md")

# Cache: tag -> dict of loaded templates
_template_cache: dict[str, Optional[dict]] = {}


def load_profile() -> str:
    """Load profile.yaml as raw text for the prompt."""
    with open(PROFILE_PATH, "r") as f:
        return f.read()


def load_signature(for_tag: str) -> str:
    """Load HTML email signature for a given tag. Returns empty string if not found."""
    path = os.path.join(TEMPLATES_DIR, for_tag, "signature.html")
    if not os.path.isfile(path):
        return ""
    with open(path, "r") as f:
        return f.read().strip()


def load_email_skills() -> str:
    """Load email skills/guidelines. Returns empty string if not found."""
    if not os.path.isfile(EMAIL_SKILLS_PATH):
        return ""
    with open(EMAIL_SKILLS_PATH, "r") as f:
        return f.read()


def load_templates(for_tag: str) -> Optional[dict]:
    """Load email templates for a given tag. Returns None if introductory_email.md missing."""
    if for_tag in _template_cache:
        return _template_cache[for_tag]

    tag_dir = os.path.join(TEMPLATES_DIR, for_tag)
    intro_path = os.path.join(tag_dir, "introductory_email.md")

    if not os.path.isfile(intro_path):
        _template_cache[for_tag] = None
        return None

    templates = {}
    with open(intro_path, "r") as f:
        templates["introductory_email"] = f.read()

    for name in ("case_studies", "offerings"):
        path = os.path.join(tag_dir, f"{name}.md")
        if os.path.isfile(path):
            with open(path, "r") as f:
                templates[name] = f.read()

    _template_cache[for_tag] = templates
    return templates


def parse_json_response(text: str) -> dict:
    """Parse JSON from Claude response, stripping code fences if present."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else text[3:]
    text = text.rstrip("`").strip()
    return json.loads(text)


# ── Phase 1: Web Research ──

def do_research(person: dict) -> dict:
    """Use Claude with web_search tool to research the person and their org."""
    org = person.get("organization") or ""
    name = person.get("name") or ""

    prompt = f"""Research the following person and their organization for a sales outreach email about sustainability/climate training.

Person: {name}
Title: {person.get('title') or 'Unknown'}
Organization: {org}
Industry: {person.get('org_industry') or 'Unknown'}

Do the following searches:
1. Search for "{org} sustainability news" to find recent sustainability initiatives, ESG reports, net-zero commitments, or climate-related announcements
2. Search for "{name} {org}" to find recent news, talks, or publications about this person
3. If the first searches don't yield much, try variations like "{org} ESG" or "{org} climate commitment"

After researching, return a JSON object with this exact structure:
{{
  "org_news": [
    {{"headline": "...", "summary": "one sentence", "date": "YYYY-MM or approximate", "url": "..."}}
  ],
  "person_news": [
    {{"headline": "...", "summary": "one sentence", "date": "YYYY-MM or approximate", "url": "..."}}
  ],
  "talking_points": [
    "A specific, actionable talking point referencing the research"
  ],
  "search_quality": "high|medium|low"
}}

Rules:
- org_news: Up to 3 most relevant recent items. Empty array if nothing found.
- person_news: Up to 2 items about the person specifically. Empty array if nothing found.
- talking_points: 2-4 specific points that could be woven into an outreach email. Reference actual findings.
- search_quality: "high" if you found recent sustainability news, "medium" if only general info, "low" if very little found.
- Return ONLY the JSON object, no other text."""

    print("  Phase 1: Researching...")

    for attempt in range(3):
        try:
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=CLAUDE_MAX_TOKENS,
                tools=[{
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": 5,
                }],
                messages=[{"role": "user", "content": prompt}],
            )
            break
        except anthropic.RateLimitError:
            wait = 2 ** attempt * 5
            print(f"  Rate limited, waiting {wait}s...")
            time.sleep(wait)
    else:
        raise RuntimeError("Claude API rate limit exceeded after 3 retries")

    # Extract text from response (may contain tool_use blocks interspersed)
    text = ""
    for block in response.content:
        if block.type == "text":
            text += block.text

    if not text.strip():
        raise RuntimeError("No text response from research phase")

    research = parse_json_response(text)

    # Log summary
    org_count = len(research.get("org_news", []))
    person_count = len(research.get("person_news", []))
    quality = research.get("search_quality", "unknown")
    print(f"  Found {org_count} org news, {person_count} person news (quality: {quality})")

    return research


# ── Phase 2: Draft Email ──

def draft_email(person: dict, research: dict, profile_text: str, templates: dict, tone: str, signature: str, email_skills: str) -> dict:
    """Call Claude to draft an email using research findings."""
    scheduling_link = os.environ.get("SCHEDULING_LINK", "https://calendly.com/bapnaa/30min")

    parts = [
        "You are drafting a personalized cold outreach email on behalf of a founder. "
        "Return ONLY valid JSON with keys \"subject\" and \"body\". No other text.",
        "",
    ]

    if email_skills:
        parts += [
            "## Email Drafting Guidelines (follow these strictly)",
            email_skills,
            "",
        ]

    parts += [
        "## Founder Profile",
        profile_text,
        "",
        "## Email Template (structural guide — do NOT copy verbatim)",
        templates["introductory_email"],
        "",
    ]

    if "case_studies" in templates:
        parts += [
            "## Case Studies Library",
            "Pick exactly 2-3 case studies most relevant to the recipient's industry, role, and org type. "
            "Preserve the original hyperlinks exactly as written.",
            templates["case_studies"],
            "",
        ]

    if "offerings" in templates:
        parts += [
            "## Offerings Catalog",
            "Optionally reference ONE course/offering ONLY if it is highly relevant to the recipient's role. "
            "Do not force it.",
            templates["offerings"],
            "",
        ]

    # Research findings
    parts += [
        "## Research Findings (use these to personalize the email)",
        json.dumps(research, indent=2),
        "",
    ]

    parts += [
        "## Recipient",
        f"Name: {person['name']}",
        f"Title: {person.get('title') or 'Unknown'}",
        f"Organization: {person.get('organization') or 'Unknown'}",
        f"Context: {person.get('context') or 'None'}",
        f"Org Industry: {person.get('org_industry') or 'Unknown'}",
        f"Org Employee Count: {person.get('org_employee_count') or 'Unknown'}",
        f"Seniority: {person.get('seniority') or 'Unknown'}",
        f"Shared Background: {person.get('shared_background') or 'None'}",
        f"Priority Reasons: {person.get('priority_reasons') or 'None'}",
        "",
        f"Scheduling link: {scheduling_link}",
        "",
        "## Instructions",
        f"- Use the \"{tone}\" tone as described in the Email Drafting Guidelines above.",
        "- Weave in 1-2 specific research findings naturally — reference their actual sustainability "
        "initiatives, recent news, or the person's public work. Do NOT be generic.",
        "- Rewrite the raw <context> into a natural opening. Do NOT paste it verbatim.",
        "- Pick exactly 2-3 case studies from the library above with hyperlinks preserved as markdown links.",
        "- Subject line: under 60 characters, personal, no salesy/clickbait language.",
        "- Body: 5-8 sentences max (excluding case study bullet points).",
        "- End with the scheduling link for booking a call.",
        f"- End the email with this exact HTML signature (do not modify it):\n{signature}" if signature else "- Sign off as 'Anshuman'.",
        "",
        "## Output Format",
        '- The "subject" value must be plain text.',
        '- The "body" value MUST be valid HTML using only: <p>, <br>, <strong>, <em>, <u>, <a href="...">, <ul>, <ol>, <li>. '
        "No markdown, no <div>, <span>, or inline styles. "
        "Wrap each paragraph in <p> tags. Use <a href> for all links. Use <ul>/<li> for bullet lists.",
        "",
        "Return ONLY valid JSON:",
        '{"subject": "...", "body": "<p>...</p>"}',
    ]

    prompt = "\n".join(parts)

    print("  Phase 2: Drafting email...")

    for attempt in range(3):
        try:
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=CLAUDE_MAX_TOKENS,
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
    return parse_json_response(text)


# ── Phase 3: Save ──

def save_to_db(person: dict, result: dict, research: dict, tone: str, force: bool):
    """Upsert outreach row and update person status."""
    research_json = json.dumps(research)

    # Check for existing outreach
    existing = supabase.table("outreach").select("id").eq("person_id", person["id"]).execute()

    if existing.data:
        # Update existing row
        supabase.table("outreach").update({
            "subject": result["subject"],
            "body": result["body"],
            "research_notes": research_json,
            "tone": tone,
            "status": "drafted",
        }).eq("id", existing.data[0]["id"]).execute()
    else:
        # Insert new row
        supabase.table("outreach").insert({
            "person_id": person["id"],
            "channel": "email",
            "subject": result["subject"],
            "body": result["body"],
            "research_notes": research_json,
            "tone": tone,
            "status": "drafted",
        }).execute()

    # Update person status
    supabase.table("people").update({
        "status": "outreach_drafted",
    }).eq("id", person["id"]).execute()

    print("  Phase 3: Saved to DB")


def main():
    parser = argparse.ArgumentParser(description="Research-enhanced email drafting agent")
    parser.add_argument("--person-id", required=True, help="Person UUID to draft for")
    parser.add_argument("--tone", choices=["warm", "professional"], default="warm", help="Email tone (default: warm)")
    parser.add_argument("--for-tag", help="Override person's for_tag for template selection")
    parser.add_argument("--dry-run", action="store_true", help="Preview without DB writes")
    parser.add_argument("--force", action="store_true", help="Re-draft even if outreach row exists")
    args = parser.parse_args()

    # Fetch person
    result = supabase.table("people").select("*").eq("id", args.person_id).execute()
    if not result.data:
        print(f"Person not found: {args.person_id}")
        sys.exit(1)

    person = result.data[0]
    tag = args.for_tag or person.get("for_tag") or ""

    print(f"=== Research & Draft: {person['name']} | {person.get('organization', '')} | tone={args.tone} ===\n")

    # Check for existing draft (unless --force)
    if not args.force:
        existing = supabase.table("outreach").select("id").eq("person_id", person["id"]).execute()
        if existing.data:
            print("Draft already exists. Use --force to re-draft.")
            sys.exit(0)

    # Load templates
    templates = load_templates(tag)
    if templates is None:
        print(f"No introductory_email.md template for tag '{tag}'")
        sys.exit(1)

    profile_text = load_profile()
    signature = load_signature(tag)
    email_skills = load_email_skills()

    try:
        # Phase 1: Research
        research = do_research(person)

        # Phase 2: Draft
        email = draft_email(person, research, profile_text, templates, args.tone, signature, email_skills)
        subject = email["subject"]
        body = email["body"]

        print(f"\n  Subject: {subject}")
        preview = body[:200] + ("..." if len(body) > 200 else "")
        print(f"  Body preview: {preview}")

        # Phase 3: Save
        if not args.dry_run:
            save_to_db(person, email, research, args.tone, args.force)
        else:
            print("\n  [DRY RUN] Would save to DB")
            print(f"  Research: {json.dumps(research, indent=2)[:500]}...")

        print("\n=== Done ===")

    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
