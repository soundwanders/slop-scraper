#!/usr/bin/env python3
"""
One-time cleanup: normalize release_date values already in the database
to ISO format (YYYY-MM-DD) so the web app can sort on them.

Steam stores dates as human strings ("8 Feb, 2018", "Mar 14, 2006") and
the scraper used to save them verbatim. The scraper now normalizes at
save time (utils/dates.py); this script fixes the rows written before.

Usage (from the repo root, after any running scrape finishes):
    python3 slop_scraper/fix_dates.py            # dry run — shows what would change
    python3 slop_scraper/fix_dates.py --apply    # actually update the database
"""

import os
import sys
import argparse

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from dotenv import load_dotenv

# Same .env discovery as backfill.py
for env_file in ['.env', '../.env', os.path.join(current_dir, '..', '.env')]:
    if os.path.exists(env_file):
        load_dotenv(env_file)
        break

from utils.dates import normalize_release_date
from database.supabase import setup_supabase_connection


def main():
    parser = argparse.ArgumentParser(description='Normalize release_date values to ISO format')
    parser.add_argument('--apply', action='store_true',
                        help='Write changes to the database (default is a dry run)')
    args = parser.parse_args()

    print("🔗 Connecting to Supabase...")
    supabase = setup_supabase_connection()
    if not supabase:
        print("❌ Failed to connect to database")
        sys.exit(1)

    print("📥 Fetching all games...")
    # Supabase caps selects at 1000 rows by default — paginate to get everything
    games = []
    page_size = 1000
    start = 0
    while True:
        response = (supabase.table('games')
                    .select('app_id, title, release_date')
                    .range(start, start + page_size - 1)
                    .execute())
        batch = response.data or []
        games.extend(batch)
        if len(batch) < page_size:
            break
        start += page_size
    print(f"   {len(games)} games in database")

    updates = []
    unparseable = []
    already_ok = 0
    empty = 0

    for game in games:
        raw = game.get('release_date')
        if not raw or not str(raw).strip():
            empty += 1
            continue

        normalized = normalize_release_date(raw)
        if normalized == str(raw).strip():
            # Either already ISO or unparseable (normalizer returns input as-is)
            import re
            if re.match(r'^\d{4}-\d{2}-\d{2}$', normalized):
                already_ok += 1
            else:
                unparseable.append(game)
        else:
            updates.append({'app_id': game['app_id'], 'title': game['title'],
                            'old': raw, 'new': normalized})

    print(f"\n📊 Analysis:")
    print(f"   Already ISO:  {already_ok}")
    print(f"   Empty:        {empty}")
    print(f"   To normalize: {len(updates)}")
    print(f"   Unparseable:  {len(unparseable)}")

    if updates:
        print(f"\nSample conversions:")
        for u in updates[:8]:
            print(f"   {u['title'][:35]:35} '{u['old']}' → '{u['new']}'")

    if unparseable:
        print(f"\n⚠️ Unparseable (left untouched — review manually):")
        for g in unparseable[:15]:
            print(f"   app_id={g['app_id']:<8} '{g['release_date']}'  ({g.get('title', '?')[:40]})")

    if not updates:
        print("\n✅ Nothing to update.")
        return

    if not args.apply:
        print(f"\n🔍 DRY RUN — re-run with --apply to update {len(updates)} rows")
        return

    print(f"\n💾 Updating {len(updates)} rows...")
    errors = 0
    for u in updates:
        try:
            supabase.table('games').update(
                {'release_date': u['new']}
            ).eq('app_id', u['app_id']).execute()
        except Exception as e:
            errors += 1
            print(f"   ⚠️ Failed for app_id={u['app_id']}: {e}")

    print(f"✅ Done — {len(updates) - errors} updated, {errors} errors")


if __name__ == '__main__':
    main()
