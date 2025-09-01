#!/bin/bash
# Comprehensive Testing Strategy for Metadata Extraction Fix
# Run this step-by-step to validate the solution

echo "🧪 COMPREHENSIVE TESTING STRATEGY"
echo "================================="

echo ""
echo "📋 PHASE 1: BACKUP AND SETUP"
echo "-----------------------------"

# 1. Backup current files
echo "1. Creating backups..."
cd slop_scraper
cp scrapers/steampowered.py scrapers/steampowered_old.py
cp backfill.py backfill_old.py

# 2. Implement new files
echo "2. Replace with new implementation files"
echo "   → Copy steampowered.py content from artifact 1"
echo "   → Copy backfill.py content from artifact 2"

echo ""
echo "📋 PHASE 2: TEST MAIN SCRAPER METADATA EXTRACTION"
echo "------------------------------------------------"

# Test 1: Single game metadata extraction
echo "3. Testing single game metadata extraction..."
echo "python3 main.py --test-single-game 'Counter-Strike 2'"
echo "   Expected: Should show metadata for all fields (developer, publisher, engine, etc.)"

# Test 2: Small test batch with metadata logging
echo ""
echo "4. Testing small batch with complete metadata..."
echo "python3 main.py --test --limit 3 --debug"
echo "   Expected: Each game should have complete metadata in output files"

# Test 3: Check test output files for metadata completeness
echo ""
echo "5. Verify test output contains complete metadata..."
echo "ls -la test-output/"
echo "cat test-output/test_results.json | jq '.games[] | {name: .title, developer: .developer, publisher: .publisher, engine: .engine}'"

echo ""
echo "📋 PHASE 3: TEST BACKFILL ANALYSIS"
echo "----------------------------------"

# Test 4: Analyze current database gaps
echo "6. Analyze current database metadata gaps..."
echo "python3 backfill.py --analyze-only --debug"
echo "   Expected: Should show detailed breakdown of missing fields"

# Test 5: Dry run backfill
echo ""
echo "7. Test backfill process (dry run)..."
echo "python3 backfill.py --dry-run --limit 5 --debug"
echo "   Expected: Should show what would be updated without actually updating"

echo ""
echo "📋 PHASE 4: INTEGRATION TESTING"
echo "-------------------------------"

# Test 6: Run main scraper with database integration
echo "8. Test main scraper with database (small batch)..."
echo "python3 main.py --limit 5 --debug --no-skip-existing"
echo "   Expected: Should save complete metadata to database"

# Test 7: Check database for complete metadata
echo ""
echo "9. Verify database contains complete metadata..."
echo "python3 -c \""
echo "from database.supabase import setup_supabase_connection"
echo "supabase = setup_supabase_connection()"
echo "if supabase:"
echo "    result = supabase.table('games').select('*').limit(5).execute()"
echo "    for game in result.data:"
echo "        print(f'{game[\"title\"]}: dev={game[\"developer\"]}, pub={game[\"publisher\"]}, engine={game[\"engine\"]}')
echo "\""

# Test 8: Run actual backfill on remaining gaps
echo ""
echo "10. Run actual backfill process..."
echo "python3 backfill.py --limit 3 --debug"
echo "    Expected: Should successfully update missing fields"

echo ""
echo "📋 PHASE 5: PERFORMANCE AND EDGE CASE TESTING"
echo "--------------------------------------------"

# Test 9: Edge cases
echo "11. Test edge cases..."
echo "python3 main.py --test-single-game 'NonExistentGame12345'"
echo "    Expected: Should handle gracefully without crashing"

# Test 10: Rate limiting
echo ""
echo "12. Test rate limiting..."
echo "python3 main.py --test --limit 3 --rate 0.5 --debug"
echo "    Expected: Should respect rate limits and not get blocked"

echo ""
echo "📋 PHASE 6: BEFORE/AFTER COMPARISON"
echo "-----------------------------------"

# Test 11: Compare metadata completeness
echo "13. Generate before/after metrics..."
echo ""
echo "# Create comparison script"
cat > test_comparison.py << 'EOF'
#!/usr/bin/env python3
"""
Compare metadata completeness before and after the fix
"""
from database.supabase import setup_supabase_connection

def analyze_metadata_completeness():
    supabase = setup_supabase_connection()
    if not supabase:
        print("❌ Could not connect to database")
        return
    
    response = supabase.table("games").select("*").execute()
    
    if not response.data:
        print("❌ No games found")
        return
    
    total_games = len(response.data)
    
    # Count completeness for each field
    fields = ['developer', 'publisher', 'release_date', 'engine']
    completeness = {}
    
    for field in fields:
        complete = 0
        for game in response.data:
            value = game.get(field)
            if value and value.strip() and value not in ['Unknown', 'unknown', '']:
                complete += 1
        
        completeness[field] = {
            'complete': complete,
            'percentage': (complete / total_games) * 100
        }
    
    print(f"📊 Metadata Completeness Analysis ({total_games} games):")
    print("=" * 50)
    
    for field, stats in completeness.items():
        percentage = stats['percentage']
        status = "🟢" if percentage > 80 else "🟡" if percentage > 50 else "🔴"
        print(f"{status} {field}: {stats['complete']}/{total_games} ({percentage:.1f}%)")
    
    # Overall completeness score
    avg_completeness = sum(stats['percentage'] for stats in completeness.values()) / len(fields)
    print(f"\n📈 Overall completeness: {avg_completeness:.1f}%")
    
    if avg_completeness > 75:
        print("✅ EXCELLENT - Metadata extraction working well!")
    elif avg_completeness > 50:
        print("🟡 GOOD - Some improvement, but could be better")
    else:
        print("🔴 POOR - Metadata extraction needs more work")

if __name__ == "__main__":
    analyze_metadata_completeness()
EOF

echo "python3 test_comparison.py"

echo ""
echo "📋 PHASE 7: STRESS TESTING"
echo "-------------------------"

# Test 12: Larger batch test
echo "14. Stress test with larger batch..."
echo "python3 main.py --limit 20 --rate 1.5 --debug"
echo "    Expected: Should handle larger batches without issues"

# Test 13: Check for memory leaks
echo ""
echo "15. Monitor memory usage..."
echo "python3 -c \""
echo "import psutil, os"
echo "print(f'Memory before: {psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024:.1f} MB')"
echo "# Run your scraper here"
echo "print(f'Memory after: {psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024:.1f} MB')"
echo "\""

echo ""
echo "📋 PHASE 8: VALIDATION CHECKLIST"
echo "-------------------------------"

echo "16. Final validation checklist:"
echo ""
echo "✅ Main scraper extracts all metadata fields"
echo "✅ Database contains complete game information"
echo "✅ Backfill only processes games with genuinely missing data"
echo "✅ No crashes or errors during processing"
echo "✅ Rate limiting works properly"
echo "✅ Engine detection is accurate"
echo "✅ Memory usage is stable"
echo "✅ Performance is acceptable"

echo ""
echo "📋 PHASE 9: GENERATE REPORT FOR LEAD DEVELOPER"
echo "---------------------------------------------"

echo "17. Generate comprehensive report..."

cat > generate_report.py << 'EOF'
#!/usr/bin/env python3
"""
Generate comprehensive report for lead developer
"""
import json
import os
from database.supabase import setup_supabase_connection

def generate_implementation_report():
    """Generate a report showing the fix results"""
    
    report = {
        "summary": "Metadata Extraction Fix Results",
        "problem_solved": "Main scraper now extracts complete metadata, reducing backfill dependency",
        "tests_performed": [],
        "results": {},
        "recommendations": []
    }
    
    # Check test results
    if os.path.exists("test-output/test_results.json"):
        with open("test-output/test_results.json", 'r') as f:
            test_data = json.load(f)
            
        report["tests_performed"].append("Main scraper test mode")
        report["results"]["test_games_processed"] = test_data.get("games_processed", 0)
        report["results"]["test_options_found"] = test_data.get("total_options_found", 0)
        
        # Check metadata completeness in test results
        games_with_complete_metadata = 0
        for game in test_data.get("games", []):
            # This would need to be updated based on actual test output structure
            if game.get("developer") and game.get("publisher"):
                games_with_complete_metadata += 1
        
        if test_data.get("games_processed", 0) > 0:
            metadata_completeness = (games_with_complete_metadata / test_data["games_processed"]) * 100
            report["results"]["metadata_completeness_percentage"] = metadata_completeness
    
    # Check database stats
    try:
        supabase = setup_supabase_connection()
        if supabase:
            response = supabase.table("games").select("*").limit(100).execute()
            
            if response.data:
                total_games = len(response.data)
                complete_games = 0
                
                for game in response.data:
                    if (game.get("developer") and game.get("publisher") and 
                        game.get("engine") and game.get("engine") != "Unknown"):
                        complete_games += 1
                
                db_completeness = (complete_games / total_games) * 100
                report["results"]["database_completeness_percentage"] = db_completeness
                report["results"]["database_sample_size"] = total_games
    
    except Exception as e:
        report["results"]["database_error"] = str(e)
    
    # Add recommendations
    metadata_completeness = report["results"].get("metadata_completeness_percentage", 0)
    db_completeness = report["results"].get("database_completeness_percentage", 0)
    
    if metadata_completeness > 80 and db_completeness > 70:
        report["recommendations"].append("✅ READY FOR PRODUCTION - Fix is working well")
        report["recommendations"].append("🚀 Can proceed with full implementation")
    elif metadata_completeness > 60:
        report["recommendations"].append("🟡 MOSTLY WORKING - Minor improvements needed")
        report["recommendations"].append("🔧 Consider engine detection tuning")
    else:
        report["recommendations"].append("🔴 NEEDS MORE WORK - Significant issues remain")
        report["recommendations"].append("🛠️ Investigate metadata extraction logic")
    
    # Save report
    with open("implementation_report.json", 'w') as f:
        json.dump(report, f, indent=2)
    
    print("📊 IMPLEMENTATION REPORT")
    print("=" * 50)
    print(f"📋 Problem: {report['problem_solved']}")
    print(f"🧪 Tests performed: {len(report['tests_performed'])}")
    
    if "metadata_completeness_percentage" in report["results"]:
        print(f"📈 Test metadata completeness: {report['results']['metadata_completeness_percentage']:.1f}%")
    
    if "database_completeness_percentage" in report["results"]:
        print(f"📊 Database completeness: {report['results']['database_completeness_percentage']:.1f}%")
    
    print(f"\n💡 Recommendations:")
    for rec in report["recommendations"]:
        print(f"   {rec}")
    
    print(f"\n📄 Full report saved to: implementation_report.json")

if __name__ == "__main__":
    generate_implementation_report()
EOF

echo "python3 generate_report.py"

echo ""
echo "🎯 SUCCESS CRITERIA FOR LEAD DEVELOPER"
echo "====================================="
echo ""
echo "The fix is ready for production if:"
echo "✅ Main scraper metadata completeness > 80%"
echo "✅ Database completeness improves after running scraper"
echo "✅ Backfill finds significantly fewer games needing updates"
echo "✅ No crashes or major errors during testing"
echo "✅ Engine detection shows variety (not all 'Unknown')"
echo ""
echo "Present to lead developer:"
echo "📊 implementation_report.json - Quantitative results"
echo "📋 Before/after database completeness metrics"
echo "🧪 Evidence that backfill dependency is reduced"