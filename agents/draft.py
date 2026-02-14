#!/usr/bin/env python3
"""Email drafting agent: auto-draft personalized cold emails for scored people."""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Optional, List

import anthropic
from config import supabase, ANTHROPIC_API_KEY, CLAUDE_MODEL, CLAUDE_MAX_TOKENS

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

PROFILE_PATH = "profile.yaml"
TEMPLATES_DIR = "templates"
EMAIL_SKILLS_PATH = os.path.join(TEMPLATES_DIR, "email_skills.md")

# Cache: tag → dict of loaded templates
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


def build_prompt(person: dict, profile_text: str, templates: dict, signature: str, email_skills: str) -> str:
    """Build the Claude prompt for drafting an email."""
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
        "- Rewrite the raw <context> into a natural, warm opening sentence. Do NOT paste it verbatim.",
        "- Pick exactly 2-3 case studies from the library above with hyperlinks preserved as markdown links.",
        "- Subject line: under 60 characters, personal, no salesy/clickbait language.",
        "- Body: 5-8 sentences max (excluding case study bullet points).",
        "- Tone: professional but warm, founder-to-executive. Not pushy.",
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

    return "\n".join(parts)


def draft_email(person: dict, profile_text: str, templates: dict, signature: str, email_skills: str) -> dict:
    """Call Claude to draft an email. Returns {subject, body}."""
    prompt = build_prompt(person, profile_text, templates, signature, email_skills)

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
    # Strip code fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else text[3:]
    text = text.rstrip("`").strip()

    return json.loads(text)


def get_people_to_draft(
    person_id: Optional[str] = None,
    for_tag: Optional[str] = None,
    min_score: int = 40,
) -> List[dict]:
    """Fetch scored people eligible for drafting."""
    query = supabase.table("people").select("*")

    if person_id:
        # Bypass status/score filters for single-person mode
        query = query.eq("id", person_id)
    else:
        query = query.eq("status", "enriched")
        query = query.not_.is_("priority_score", "null")
        query = query.gte("priority_score", min_score)

    if for_tag:
        query = query.eq("for_tag", for_tag)

    result = query.execute()
    return result.data


def get_already_drafted_ids() -> set:
    """Return set of person_ids that already have an outreach row."""
    result = supabase.table("outreach").select("person_id").execute()
    return {row["person_id"] for row in result.data}


def main():
    parser = argparse.ArgumentParser(description="Email drafting agent: draft personalized outreach emails")
    parser.add_argument("--person-id", help="Draft for a single person by UUID (bypasses status/score filters)")
    parser.add_argument("--for-tag", help="Only draft for people with this tag")
    parser.add_argument("--min-score", type=int, default=40, help="Minimum priority_score to draft (default: 40)")
    parser.add_argument("--dry-run", action="store_true", help="Preview drafts without DB writes")
    parser.add_argument("--force", action="store_true", help="Re-draft even if outreach row already exists")
    args = parser.parse_args()

    profile_text = load_profile()
    email_skills = load_email_skills()

    people = get_people_to_draft(args.person_id, args.for_tag, args.min_score)
    if not people:
        print("No people to draft for (check status/score filters).")
        return

    # Filter out already-drafted unless --force
    if not args.force:
        already_drafted = get_already_drafted_ids()
        before = len(people)
        people = [p for p in people if p["id"] not in already_drafted]
        skipped_existing = before - len(people)
        if skipped_existing:
            print(f"Skipping {skipped_existing} already-drafted person(s). Use --force to re-draft.")
    else:
        skipped_existing = 0

    if not people:
        print("No people to draft for (all already drafted).")
        return

    print(f"Drafting emails for {len(people)} person(s)...\n")

    drafted = 0
    skipped = skipped_existing
    errors = 0

    for i, person in enumerate(people):
        tag = person.get("for_tag") or ""
        print(f"--- [{i+1}/{len(people)}] {person['name']} | {person.get('organization', '')} | tag={tag}")

        # Load templates for this person's tag
        templates = load_templates(tag)
        if templates is None:
            print(f"  SKIP: no introductory_email.md template for tag '{tag}'")
            skipped += 1
            continue

        try:
            signature = load_signature(tag)
            result = draft_email(person, profile_text, templates, signature, email_skills)
            subject = result["subject"]
            body = result["body"]

            print(f"  Subject: {subject}")
            # Show first 200 chars of body as preview
            preview = body[:200] + ("..." if len(body) > 200 else "")
            print(f"  Body preview: {preview}")

            if not args.dry_run:
                # Insert outreach row
                supabase.table("outreach").insert({
                    "person_id": person["id"],
                    "channel": "email",
                    "subject": subject,
                    "body": body,
                    "status": "drafted",
                }).execute()

                # Update person status
                supabase.table("people").update({
                    "status": "outreach_drafted",
                }).eq("id", person["id"]).execute()

                print("  ✓ Saved to DB")
            else:
                print("  [DRY RUN] Would save to DB")

            drafted += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            errors += 1

        # Small delay between people
        if i < len(people) - 1:
            time.sleep(0.5)

    print(f"\n=== Summary ===")
    print(f"People processed: {drafted + errors}")
    print(f"Drafts created:   {drafted}")
    print(f"Skipped:          {skipped}")
    print(f"Errors:           {errors}")

    if errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
