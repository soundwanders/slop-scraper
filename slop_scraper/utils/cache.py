import json
import os

def load_cache(cache_file):
  """
  Load cache from a file.
  
  Args:
    cache_file (str): Path to the cache file.
  
  Returns:
    dict: The loaded cache data, or an empty dictionary if the file doesn't exist or is invalid.
  """
  if os.path.exists(cache_file):
    try:
      with open(cache_file, 'r') as f:
        return json.load(f)
    except json.JSONDecodeError:
      print("⚠️ Cache file is corrupt. Starting fresh.")
      return {}
    except Exception as e:
      print(f"⚠️ Error loading cache: {e}")
      return {}
  return {}

def save_cache(cache, cache_file):
  """
  Save cache to a file.
  
  Args:
    cache (dict): The cache data to save.
    cache_file (str): Path to the cache file.
  """
  try:
      with open(cache_file, 'w') as f:
        json.dump(cache, f, indent=2)
      print(f"✅ Cache saved to {cache_file}")
  except Exception as e:
    print(f"⚠️ Error saving cache: {e}")