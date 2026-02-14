"""Apollo People Match API wrapper."""

import time
from typing import Optional

import requests
from config import APOLLO_API_KEY

APOLLO_MATCH_URL = "https://api.apollo.io/api/v1/people/match"
RATE_LIMIT_DELAY = 1.2  # seconds between calls


def match_person(
    first_name: str,
    last_name: str,
    organization_name: str = "",
    linkedin_url: str = "",
    email: str = "",
) -> Optional[dict]:
    """Match a person via Apollo People Match API.

    Returns normalized dict with email, linkedin_url, title, city, state,
    country, organization_name — or None if no match.
    """
    if not APOLLO_API_KEY:
        raise RuntimeError("APOLLO_API_KEY not set in environment")

    # Only include non-empty fields — Apollo 422s on empty strings
    payload = {}
    if first_name:
        payload["first_name"] = first_name
    if last_name:
        payload["last_name"] = last_name
    if organization_name:
        payload["organization_name"] = organization_name
    if linkedin_url:
        payload["linkedin_url"] = linkedin_url
    if email:
        payload["email"] = email

    if not payload:
        return None
    headers = {
        "X-Api-Key": APOLLO_API_KEY,
        "Content-Type": "application/json",
    }

    for attempt in range(3):
        try:
            resp = requests.post(APOLLO_MATCH_URL, json=payload, headers=headers, timeout=30)

            if resp.status_code == 429:
                wait = 10 * (2 ** attempt)
                print(f"  Apollo rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue

            resp.raise_for_status()
            data = resp.json()
            break
        except requests.exceptions.HTTPError:
            if resp.status_code == 429:
                continue
            if resp.status_code == 422:
                # Validation error — log details but treat as no match
                print(f"  Apollo 422: {resp.text[:200]}")
                return None
            raise
    else:
        raise RuntimeError("Apollo API rate limit exceeded after 3 retries")

    person = data.get("person")
    if not person:
        return None

    org = person.get("organization") or {}

    return {
        # Key fields for people table columns
        "email": person.get("email") or "",
        "email_status": person.get("email_status") or "",
        "linkedin_url": person.get("linkedin_url") or "",
        "title": person.get("title") or "",
        "headline": person.get("headline") or "",
        "city": person.get("city") or "",
        "state": person.get("state") or "",
        "country": person.get("country") or "",
        "seniority": person.get("seniority") or "",
        "departments": person.get("departments") or [],
        "photo_url": person.get("photo_url") or "",
        "twitter_url": person.get("twitter_url") or "",
        "github_url": person.get("github_url") or "",
        # Org fields for filterable columns
        "organization_name": org.get("name") or "",
        "org_employee_count": org.get("estimated_num_employees"),
        "org_revenue": org.get("annual_revenue"),
        "org_total_funding": org.get("total_funding"),
        "org_industry": org.get("industry") or "",
        # Full raw response for future use
        "raw": person,
    }
