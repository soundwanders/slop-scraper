#!/usr/bin/env python3
"""
One-time backfill: tag every existing launch_options row with risk_level,
categories, and engine_compatibility (added in response to the 2026-07 site
audit — see migrations/001_add_launch_option_metadata.sql).

This makes NO network calls. classify_option_metadata() is a pure function of
the command string (and source) already stored in the database, so every row
scraped before this feature existed can be tagged retroactively without
re-scraping a single game.

Usage (from the repo root, AFTER running the migration in the Supabase SQL
editor):
    python3 slop_scraper/backfill_metadata.py            # dry run
    python3 slop_scraper/backfill_metadata.py --apply     # write to the database
"""

import os
import sys
import argparse
from collections import Counter

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from dotenv import load_dotenv

for env_file in ['.env', '../.env', os.path.join(current_dir, '..', '.env')]:
    if os.path.exists(env_file):
        load_dotenv(env_file)
        break

from validation import classify_option_metadata
from database.supabase import setup_supabase_connection


def main():
    parser = argparse.ArgumentParser(description='Backfill risk/category/engine metadata onto existing launch_options rows')
    parser.add_argument('--apply', action='store_true',
                        help='Write changes to the database (default is a dry run)')
    args = parser.parse_args()

    print("🔗 Connecting to Supabase...")
    supabase = setup_supabase_connection()
    if not supabase:
        print("❌ Failed to connect to database")
        sys.exit(1)

    print("📥 Fetching all launch_options...")
    rows = []
    page_size = 1000
    start = 0
    try:
        while True:
            response = (supabase.table('launch_options')
                        .select('id, command, source, risk_level, categories, engine_compatibility')
                        .range(start, start + page_size - 1)
                        .execute())
            batch = response.data or []
            rows.extend(batch)
            if len(batch) < page_size:
                break
            start += page_size
    except Exception as e:
        if '42703' in str(e) or 'does not exist' in str(e).lower():
            print("❌ Metadata columns not found — run migrations/001_add_launch_option_metadata.sql "
                  "in the Supabase SQL editor first, then re-run this script.")
            sys.exit(1)
        raise

    print(f"   {len(rows)} launch_options rows in database")

    if not rows:
        print("✅ Nothing to backfill.")
        return

    updates = []
    unchanged = 0
    risk_counts = Counter()
    category_counts = Counter()

    for row in rows:
        computed = classify_option_metadata(row['command'], source=row.get('source'))

        # Only overwrite the default placeholder state — never clobber a value
        # someone already curated by hand (e.g. manually upgraded to 'safe',
        # or manually tagged) after this backfill's first run.
        current_risk = row.get('risk_level') or 'experimental'
        current_categories = row.get('categories') or []
        current_engine = row.get('engine_compatibility') or []

        is_default_state = (
            current_risk == 'experimental'
            and current_categories in ([], ['Uncategorized'])
            and current_engine == []
        )

        if not is_default_state:
            unchanged += 1
            continue

        if (computed['risk_level'] == current_risk
                and computed['categories'] == current_categories
                and computed['engine_compatibility'] == current_engine):
            unchanged += 1
            continue

        updates.append({
            'id': row['id'],
            'command': row['command'],
            **computed
        })
        risk_counts[computed['risk_level']] += 1
        for cat in computed['categories']:
            category_counts[cat] += 1

    print(f"\n📊 Analysis:")
    print(f"   Already tagged / unchanged: {unchanged}")
    print(f"   To backfill:                {len(updates)}")

    if updates:
        print(f"\nRisk level breakdown (of rows being backfilled):")
        for risk, count in risk_counts.most_common():
            print(f"   {risk:12} {count}")

        print(f"\nCategory breakdown (of rows being backfilled):")
        for cat, count in category_counts.most_common():
            print(f"   {cat:15} {count}")

        print(f"\nSample:")
        for u in updates[:10]:
            print(f"   {u['command']:30} risk={u['risk_level']:12} "
                  f"cats={u['categories']!s:35} engine={u['engine_compatibility']}")

    if not updates:
        print("\n✅ Nothing to backfill.")
        return

    if not args.apply:
        print(f"\n🔍 DRY RUN — re-run with --apply to update {len(updates)} rows")
        return

    print(f"\n💾 Updating {len(updates)} rows...")
    errors = 0
    for u in updates:
        try:
            supabase.table('launch_options').update({
                'risk_level': u['risk_level'],
                'categories': u['categories'],
                'engine_compatibility': u['engine_compatibility']
            }).eq('id', u['id']).execute()
        except Exception as e:
            errors += 1
            print(f"   ⚠️ Failed for command={u['command']}: {e}")

    print(f"✅ Done — {len(updates) - errors} updated, {errors} errors")


if __name__ == '__main__':
    main()
