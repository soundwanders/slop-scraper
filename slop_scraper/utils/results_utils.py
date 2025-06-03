import json
import os

try:
    # Try relative imports first (when run as module)
    from .security_config import SecurityConfig
except ImportError:
    # Fall back to absolute imports (when run directly)
    import sys
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from security_config import SecurityConfig

def save_test_results(test_results, output_dir):
    """Save test results to JSON file with security validation"""
    if not test_results:
        return
    
    # Security: Validate output directory
    output_dir = SecurityConfig.validate_output_path(output_dir)
    
    try:
        # Security: Validate test_results structure
        if not isinstance(test_results, dict):
            print("⚠️ Invalid test results format")
            return
            
        # Security: Limit the size of test results data
        if len(str(test_results)) > 10 * 1024 * 1024:  # 10MB limit
            print("⚠️ Test results too large, truncating data")
            # Keep only essential data
            truncated_results = {
                'games_processed': test_results.get('games_processed', 0),
                'games_with_options': test_results.get('games_with_options', 0),
                'total_options_found': test_results.get('total_options_found', 0),
                'options_by_source': test_results.get('options_by_source', {}),
                'games': test_results.get('games', [])[:100]  # Limit to first 100 games
            }
            test_results = truncated_results
        
        output_file = os.path.join(output_dir, "test_results.json")
        
        # Security: Validate output file path
        if not output_file.startswith(output_dir):
            print("⚠️ Invalid output file path detected")
            return
            
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(test_results, f, indent=4, ensure_ascii=False)
        
        print(f"\n🔒 Test results saved securely to {output_file}")
        print(f"Games processed: {test_results['games_processed']}")
        print(f"Games with options found: {test_results['games_with_options']}")
        print(f"Total options found: {test_results['total_options_found']}")
        print("Options by source:")
        for source, count in test_results['options_by_source'].items():
            print(f"  {source}: {count}")
            
    except Exception as e:
        print(f"🔒 Error saving test results: {e}")
        print("Try running the script with sudo or check directory permissions")

def save_game_results(app_id, title, options, output_dir):
    """Save individual game results to file with security validation"""
    # Security: Validate inputs
    try:
        app_id_int = int(app_id)
        if app_id_int <= 0:
            print(f"⚠️ Invalid app_id: {app_id}")
            return
    except (ValueError, TypeError):
        print(f"⚠️ Invalid app_id format: {app_id}")
        return
    
    if not title or len(title) > 200:
        print(f"⚠️ Invalid title: {title}")
        return
    
    if not isinstance(options, list):
        print(f"⚠️ Invalid options format for {title}")
        return
    
    # Security: Validate output directory
    output_dir = SecurityConfig.validate_output_path(output_dir)
    
    try:
        # Security: Sanitize filename
        safe_app_id = str(app_id_int)
        game_file = os.path.join(output_dir, f"game_{safe_app_id}.json")
        
        # Security: Validate final file path
        if not game_file.startswith(output_dir):
            print(f"⚠️ Invalid file path detected for game {title}")
            return
        
        # Security: Limit options data size
        if len(options) > 100:
            print(f"⚠️ Too many options for {title}, limiting to first 100")
            options = options[:100]
        
        # Security: Validate each option
        validated_options = []
        for option in options:
            if (isinstance(option, dict) and 
                option.get('command') and 
                len(str(option.get('command', ''))) <= 100 and
                len(str(option.get('description', ''))) <= 500):
                validated_options.append({
                    'command': str(option.get('command', ''))[:100],
                    'description': str(option.get('description', ''))[:500],
                    'source': str(option.get('source', 'Unknown'))[:50]
                })
        
        game_data = {
            'app_id': app_id_int,
            'title': str(title)[:200],  # Limit title length
            'options': validated_options
        }
        
        with open(game_file, 'w', encoding='utf-8') as f:
            json.dump(game_data, f, indent=4, ensure_ascii=False)
            
    except Exception as e:
        print(f"🔒 Error saving game data for {title}: {e}")