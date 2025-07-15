#!/usr/bin/env python3
"""
Test script to verify the scraper fixes work correctly
"""

import os
import sys
import time

# Add the project root to Python path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

def test_individual_scrapers():
    """Test each scraper individually with the fixes"""
    print("🧪 TESTING INDIVIDUAL SCRAPER FIXES")
    print("=" * 50)
    
    test_games = [
        {"name": "Half-Life 2", "app_id": 220},
        {"name": "Counter-Strike", "app_id": 10},
        {"name": "Portal", "app_id": 400}
    ]
    
    for game in test_games:
        print(f"\n🎮 Testing with: {game['name']} (App ID: {game['app_id']})")
        print("-" * 40)
        
        # Test Game-Specific (should always work)
        print("\n1. Game-Specific Scraper (should work):")
        try:
            from scrapers.game_specific import fetch_game_specific_options
            cache = {str(game['app_id']): {'name': game['name'], 'developers': ['Valve Corporation']}}
            gs_options = fetch_game_specific_options(
                game['app_id'], game['name'], cache, test_mode=True
            )
            print(f"   ✅ Result: {len(gs_options)} options")
            for opt in gs_options[:2]:
                print(f"      - {opt['command']}: {opt['description'][:40]}...")
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        # Test FIXED PCGamingWiki  
        print("\n2. FIXED PCGamingWiki Scraper:")
        try:
            from scrapers.pcgamingwiki import fetch_pcgamingwiki_launch_options
            pcg_options = fetch_pcgamingwiki_launch_options(
                game['name'], rate_limit=2.0, debug=True, test_mode=True
            )
            print(f"   Result: {len(pcg_options)} options")
            for opt in pcg_options[:2]:
                print(f"      - {opt['command']}: {opt['description'][:40]}...")
            
            if len(pcg_options) > 0:
                print("   ✅ PCGamingWiki fix appears to be working!")
            else:
                print("   ⚠️ Still returning 0 options (may still be blocked)")
                
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        time.sleep(3)  # Be nice to servers
        
        # Test FIXED Steam Community
        print("\n3. FIXED Steam Community Scraper:")
        try:
            from scrapers.steamcommunity import fetch_steam_community_launch_options
            sc_options = fetch_steam_community_launch_options(
                game['app_id'], game_title=game['name'], 
                rate_limit=2.0, debug=True, test_mode=True
            )
            print(f"   Result: {len(sc_options)} options")
            for opt in sc_options[:2]:
                print(f"      - {opt['command']}: {opt['description'][:40]}...")
            
            if len(sc_options) > 0:
                print("   ✅ Steam Community fix appears to be working!")
            else:
                print("   ⚠️ Still returning 0 options (may need more HTML structure fixes)")
                
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        time.sleep(3)  # Be nice to servers
        
        # Test FIXED ProtonDB
        print("\n4. FIXED ProtonDB Scraper:")
        try:
            from scrapers.protondb import fetch_protondb_launch_options
            pdb_options = fetch_protondb_launch_options(
                game['app_id'], game_title=game['name'],
                rate_limit=2.0, debug=True, test_mode=True
            )
            print(f"   Result: {len(pdb_options)} options")
            for opt in pdb_options[:2]:
                print(f"      - {opt['command']}: {opt['description'][:40]}...")
            
            if len(pdb_options) > 0:
                print("   ✅ ProtonDB fix appears to be working!")
            else:
                print("   ⚠️ Still returning 0 options")
                
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        print("\n" + "=" * 50)
        time.sleep(2)  # Delay between games

def test_full_scraper():
    """Test the full scraper with all fixes"""
    print("\n🚀 TESTING FULL SCRAPER WITH FIXES")
    print("=" * 50)
    
    try:
        print("Running main scraper with debug mode and 3 games...")
        os.system("python3 main.py --limit 3 --debug-scrapers --skip-existing")
    except Exception as e:
        print(f"❌ Error running full scraper: {e}")

def main():
    """Main test function"""
    print("🔧 SCRAPER FIX VERIFICATION TEST")
    print("=" * 60)
    print("This will test the specific fixes for:")
    print("1. PCGamingWiki Cloudflare bypass")  
    print("2. Steam Community HTML structure fixes")
    print("3. ProtonDB API endpoint fixes")
    print("=" * 60)
    
    try:
        # Test individual scrapers
        test_individual_scrapers()
        
        # Test full scraper
        test_full_scraper()
        
        print("\n" + "=" * 60)
        print("🔧 FIX VERIFICATION COMPLETE")
        print("=" * 60)
        print("Expected results:")
        print("✅ Game-Specific: Should always return 5-10 options")
        print("🔄 PCGamingWiki: May still return 0 if Cloudflare blocks persist")
        print("🔄 Steam Community: Should return more options than before")
        print("🔄 ProtonDB: Should return some options for popular games")
        print()
        print("If ALL scrapers return 0 options, the issues may require")
        print("more advanced techniques (proxy servers, browser automation, etc.)")
        print("=" * 60)
        
        return True
        
    except Exception as e:
        print(f"\n❌ Test error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)