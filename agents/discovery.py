#!/usr/bin/env python3
"""Discovery agent: fetch curated sources and extract people into Supabase."""

import argparse
import sys
from datetime import datetime, timezone, timedelta

from config import supabase
from fetch import fetch_page
from extract import extract_people


def get_due_sources(source_id: str | None = None) -> list[dict]:
    """Return sources that are due for checking."""
    query = supabase.table("sources").select("*").eq("is_active", True)

    if source_id:
        query = query.eq("id", source_id)
    else:
        # Only fetch sources that haven't been checked or are past their check frequency
        query = query.or_(
            "last_checked_at.is.null,"
            f"last_checked_at.lt.{(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()}"
        )

    result = query.execute()
    # Filter in Python for accurate frequency check
    due = []
    for s in result.data:
        if source_id:
            due.append(s)
        elif s["last_checked_at"] is None:
            due.append(s)
        else:
            last = datetime.fromisoformat(s["last_checked_at"])
            freq = timedelta(hours=s["check_frequency_hours"])
            if datetime.now(timezone.utc) - last >= freq:
                due.append(s)
    return due


def process_source(source: dict, dry_run: bool = False) -> dict:
    """Process a single source. Returns summary dict."""
    url = source["url"]
    for_tag = source.get("for_tag", "other")
    print(f"\n--- Processing: {url}")

    # 1. Fetch
    try:
        text, title = fetch_page(url)
        print(f"  Fetched {len(text)} chars, title: {title[:80]}")
    except Exception as e:
        print(f"  ERROR fetching: {e}")
        return {"url": url, "error": f"fetch: {e}"}

    # 2. Extract
    try:
        people = extract_people(title, url, text)
        print(f"  Extracted {len(people)} people")
    except Exception as e:
        print(f"  ERROR extracting: {e}")
        return {"url": url, "error": f"extract: {e}"}

    if dry_run:
        for p in people:
            print(f"    - {p['name']} | {p.get('title','')} | {p.get('organization','')}")
        return {"url": url, "extracted": len(people), "inserted": 0, "skipped": 0, "dry_run": True}

    # 3. Upsert to Supabase
    inserted = 0
    skipped = 0
    for p in people:
        row = {
            "name": p["name"],
            "title": p.get("title", ""),
            "organization": p.get("organization", ""),
            "email": p.get("email", ""),
            "linkedin": p.get("linkedin", ""),
            "context": p.get("context", ""),
            "source_url": url,
            "for_tag": for_tag,
            "status": "discovered",
        }
        try:
            supabase.table("people").insert(row).execute()
            inserted += 1
        except Exception as e:
            err_str = str(e)
            if "duplicate" in err_str.lower() or "23505" in err_str:
                skipped += 1
            else:
                print(f"    ERROR inserting {p['name']}: {e}")

    print(f"  Result: {inserted} inserted, {skipped} duplicates skipped")

    # 4. Update source
    try:
        supabase.table("sources").update({
            "last_checked_at": datetime.now(timezone.utc).isoformat(),
            "last_people_count": len(people),
        }).eq("id", source["id"]).execute()
    except Exception as e:
        print(f"  WARNING: could not update source: {e}")

    return {"url": url, "extracted": len(people), "inserted": inserted, "skipped": skipped}


def main():
    parser = argparse.ArgumentParser(description="Discovery agent: extract people from curated sources")
    parser.add_argument("--source-id", help="Process a single source by UUID")
    parser.add_argument("--dry-run", action="store_true", help="Extract but don't write to DB")
    args = parser.parse_args()

    sources = get_due_sources(args.source_id)
    if not sources:
        print("No sources due for processing.")
        return

    print(f"Found {len(sources)} source(s) to process")

    results = []
    for source in sources:
        result = process_source(source, dry_run=args.dry_run)
        results.append(result)

    # Summary
    print("\n=== Summary ===")
    total_extracted = sum(r.get("extracted", 0) for r in results)
    total_inserted = sum(r.get("inserted", 0) for r in results)
    total_skipped = sum(r.get("skipped", 0) for r in results)
    total_errors = sum(1 for r in results if "error" in r)
    print(f"Sources processed: {len(results)}")
    print(f"People extracted:  {total_extracted}")
    if not args.dry_run:
        print(f"People inserted:   {total_inserted}")
        print(f"Duplicates skipped: {total_skipped}")
    print(f"Errors:            {total_errors}")

    if total_errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
