#!/usr/bin/env python3
"""Enrichment agent: enrich discovered people with Apollo data and LinkedIn connections."""

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from typing import Optional, List

from config import supabase
from apollo_client import match_person, RATE_LIMIT_DELAY


def load_connections_csv(path: str) -> List[dict]:
    """Load LinkedIn connections CSV, handling header variants."""
    connections = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Handle header variants
            first = row.get("First Name") or row.get("First name") or ""
            last = row.get("Last Name") or row.get("Last name") or ""
            email = row.get("Email Address") or row.get("Email address") or ""
            company = row.get("Company") or ""
            position = row.get("Position") or ""
            url = row.get("URL") or row.get("LinkedIn Profile URL") or ""
            connected_on = row.get("Connected On") or row.get("Connected on") or ""

            connections.append({
                "first_name": first.strip(),
                "last_name": last.strip(),
                "email": email.strip(),
                "company": company.strip(),
                "position": position.strip(),
                "linkedin_url": url.strip(),
                "connected_on": connected_on.strip(),
            })
    return connections


def find_linkedin_match(first_name: str, last_name: str, connections: List[dict]) -> Optional[dict]:
    """Fuzzy match by first+last name against loaded connections.

    Exact first+last (lowercased), fallback to first + 3-char last prefix for hyphenated names.
    """
    first_lower = first_name.lower().strip()
    last_lower = last_name.lower().strip()

    # Exact match
    for c in connections:
        if c["first_name"].lower() == first_lower and c["last_name"].lower() == last_lower:
            return c

    # Fallback: first + 3-char last prefix (for hyphenated names)
    if len(last_lower) >= 3:
        last_prefix = last_lower[:3]
        for c in connections:
            if c["first_name"].lower() == first_lower and c["last_name"].lower().startswith(last_prefix):
                return c

    return None


def log_enrichment(person_id: str, source: str, result: Optional[dict], error: Optional[str], dry_run: bool):
    """Log to enrichment_log table."""
    if dry_run:
        return
    row = {
        "person_id": person_id,
        "source": source,
        "result": json.dumps(result) if result else None,
        "error": error,
    }
    try:
        supabase.table("enrichment_log").insert(row).execute()
    except Exception as e:
        print(f"    WARNING: could not log enrichment: {e}")


def enrich_person(person: dict, connections: Optional[List[dict]], dry_run: bool) -> dict:
    """Enrich a single person. Returns summary dict."""
    pid = person["id"]
    name = person["name"]
    parts = name.split(None, 1)
    first_name = parts[0] if parts else name
    last_name = parts[1] if len(parts) > 1 else ""
    org = person.get("organization") or ""

    result = {"person_id": pid, "name": name, "apollo": False, "linkedin": False, "error": None}
    updates = {}

    # 1. Apollo match
    apollo_data = None
    try:
        apollo_data = match_person(first_name, last_name, org)
        if apollo_data:
            result["apollo"] = True
            print(f"  Apollo match: {apollo_data.get('email', '')} | {apollo_data.get('title', '')}")
            # Fill blank fields only
            if apollo_data.get("email") and not person.get("email"):
                updates["email"] = apollo_data["email"]
            if apollo_data.get("linkedin_url") and not person.get("linkedin"):
                updates["linkedin"] = apollo_data["linkedin_url"]
            if apollo_data.get("title") and not person.get("title"):
                updates["title"] = apollo_data["title"]
            # Filterable org/person columns
            if apollo_data.get("seniority"):
                updates["seniority"] = apollo_data["seniority"]
            if apollo_data.get("org_employee_count") is not None:
                updates["org_employee_count"] = apollo_data["org_employee_count"]
            if apollo_data.get("org_revenue") is not None:
                updates["org_revenue"] = int(apollo_data["org_revenue"])
            if apollo_data.get("org_total_funding") is not None:
                updates["org_total_funding"] = int(apollo_data["org_total_funding"])
            if apollo_data.get("org_industry"):
                updates["org_industry"] = apollo_data["org_industry"]
            # Store full raw Apollo response
            updates["apollo_data"] = json.dumps(apollo_data["raw"])
        else:
            print("  Apollo: no match")
    except Exception as e:
        result["error"] = f"apollo: {e}"
        print(f"  Apollo ERROR: {e}")

    log_enrichment(pid, "apollo", apollo_data, result["error"], dry_run)

    # 2. LinkedIn CSV match
    linkedin_match = None
    linkedin_error = None
    if connections is not None:
        try:
            linkedin_match = find_linkedin_match(first_name, last_name, connections)
            if linkedin_match:
                result["linkedin"] = True
                print(f"  LinkedIn 1st-degree match: {linkedin_match.get('linkedin_url', '')}")
                # Supplement blanks only
                if linkedin_match.get("email") and not person.get("email") and "email" not in updates:
                    updates["email"] = linkedin_match["email"]
                if linkedin_match.get("linkedin_url") and not person.get("linkedin") and "linkedin" not in updates:
                    updates["linkedin"] = linkedin_match["linkedin_url"]
                if linkedin_match.get("position") and not person.get("title") and "title" not in updates:
                    updates["title"] = linkedin_match["position"]
                # Append 1st-degree connection note to context
                existing_context = person.get("context") or ""
                if "[1st-degree LinkedIn connection]" not in existing_context:
                    updates["context"] = (existing_context + " [1st-degree LinkedIn connection]").strip()
            else:
                print("  LinkedIn CSV: no match")
        except Exception as e:
            linkedin_error = f"linkedin_csv: {e}"
            print(f"  LinkedIn CSV ERROR: {e}")

    log_enrichment(pid, "linkedin_csv", linkedin_match, linkedin_error, dry_run)

    # 3. Update person
    if updates:
        updates["status"] = "enriched"
        if dry_run:
            print(f"  [DRY RUN] Would update: {updates}")
        else:
            try:
                supabase.table("people").update(updates).eq("id", pid).execute()
                print(f"  Updated: {list(updates.keys())}")
            except Exception as e:
                print(f"  ERROR updating person: {e}")
                result["error"] = (result["error"] or "") + f" update: {e}"
    elif not dry_run:
        # Still mark as enriched even if no new data
        try:
            supabase.table("people").update({"status": "enriched"}).eq("id", pid).execute()
        except Exception as e:
            print(f"  WARNING: could not update status: {e}")

    return result


def get_people(person_id: Optional[str] = None, for_tag: Optional[str] = None) -> List[dict]:
    """Fetch people to enrich from Supabase."""
    query = supabase.table("people").select("*")
    if person_id:
        query = query.eq("id", person_id)
    else:
        query = query.eq("status", "discovered")
    if for_tag:
        query = query.eq("for_tag", for_tag)
    result = query.execute()
    return result.data


def main():
    parser = argparse.ArgumentParser(description="Enrichment agent: enrich people with Apollo + LinkedIn data")
    parser.add_argument("--person-id", help="Enrich a single person by UUID")
    parser.add_argument("--dry-run", action="store_true", help="Preview without DB writes")
    parser.add_argument("--connections-csv", help="Path to LinkedIn connections CSV export")
    parser.add_argument("--for-tag", help="Only enrich people with this tag")
    args = parser.parse_args()

    # Load LinkedIn connections if provided
    connections = None
    if args.connections_csv:
        connections = load_connections_csv(args.connections_csv)
        print(f"Loaded {len(connections)} LinkedIn connections from {args.connections_csv}")

    people = get_people(args.person_id, args.for_tag)
    if not people:
        print("No people to enrich.")
        return

    print(f"Found {len(people)} person(s) to enrich")

    results = []
    for i, person in enumerate(people):
        print(f"\n--- [{i+1}/{len(people)}] {person['name']} | {person.get('organization', '')}")
        result = enrich_person(person, connections, args.dry_run)
        results.append(result)

        # Rate limit between people (skip after last)
        if i < len(people) - 1:
            time.sleep(RATE_LIMIT_DELAY)

    # Summary
    print("\n=== Summary ===")
    print(f"People processed:     {len(results)}")
    print(f"Apollo matches:       {sum(1 for r in results if r['apollo'])}")
    print(f"LinkedIn 1st-degree:  {sum(1 for r in results if r['linkedin'])}")
    print(f"Records updated:      {sum(1 for r in results if r['apollo'] or r['linkedin'])}")
    print(f"Errors:               {sum(1 for r in results if r['error'])}")

    if any(r["error"] for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
