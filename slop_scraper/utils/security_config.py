import os
import time
from typing import Optional
from pathlib import Path

class SecurityConfig:
    """Security configuration and validation for slop_scraper"""
    
    # Rate limiting constraints
    MIN_RATE_LIMIT = 1.0  # Minimum 1 second between requests
    MAX_RATE_LIMIT = 60.0  # Maximum 60 seconds (sanity check)
    
    # Resource limits
    MAX_GAMES_LIMIT = 1000  # Maximum games per session
    MAX_CACHE_SIZE_MB = 100  # Maximum cache file size in MB
    MAX_EXECUTION_TIME_HOURS = 6  # Maximum runtime
    
    # File system constraints
    ALLOWED_OUTPUT_DIRS = [
        "./test-output",
        "./output", 
        "./results",
        "./data"
    ]
    
    # Network security
    MAX_REQUEST_SIZE_MB = 10  # Maximum response size
    REQUEST_TIMEOUT = 30  # Request timeout in seconds
    MAX_REDIRECTS = 3  # Maximum HTTP redirects to follow
    
    @classmethod
    def validate_rate_limit(cls, rate_limit: float) -> float:
        """Validate and enforce rate limiting constraints"""
        if rate_limit < cls.MIN_RATE_LIMIT:
            print(f"⚠️ Rate limit too low. Enforcing minimum: {cls.MIN_RATE_LIMIT}s")
            return cls.MIN_RATE_LIMIT
        elif rate_limit > cls.MAX_RATE_LIMIT:
            print(f"⚠️ Rate limit too high. Capping at: {cls.MAX_RATE_LIMIT}s")
            return cls.MAX_RATE_LIMIT
        return rate_limit
    
    @classmethod
    def validate_games_limit(cls, limit: int) -> int:
        """Validate games limit to prevent resource exhaustion"""
        if limit > cls.MAX_GAMES_LIMIT:
            print(f"⚠️ Games limit too high. Capping at: {cls.MAX_GAMES_LIMIT}")
            return cls.MAX_GAMES_LIMIT
        elif limit < 1:
            print("⚠️ Games limit must be at least 1. Setting to 1.")
            return 1
        return limit
    
    @classmethod
    def validate_output_path(cls, output_path: str, allow_absolute: bool = False) -> str:
        """Validate output path to prevent path traversal attacks"""
        try:
            # Resolve the path to handle .. and other traversal attempts
            resolved_path = Path(output_path).resolve()
            
            # For relative paths, ensure they're within safe directories
            if not allow_absolute:
                # Check if it's a subdirectory of current working directory
                cwd = Path.cwd()
                try:
                    resolved_path.relative_to(cwd)
                except ValueError:
                    print(f"⚠️ Output path outside working directory. Using default.")
                    return "./test-output"
                
                # Check against allowed directory patterns
                path_str = str(resolved_path.relative_to(cwd))
                if not any(path_str.startswith(allowed) for allowed in cls.ALLOWED_OUTPUT_DIRS):
                    # Allow if it's a subdirectory of an allowed directory
                    if not any(allowed in path_str for allowed in cls.ALLOWED_OUTPUT_DIRS):
                        print(f"⚠️ Output path not in allowed directories. Using default.")
                        return "./test-output"
            
            # Additional safety checks
            path_str = str(resolved_path)
            dangerous_patterns = ['/etc', '/var', '/usr', '/bin', '/sbin', '/sys', '/proc', 'C:\\Windows', 'C:\\Program Files']
            if any(pattern in path_str for pattern in dangerous_patterns):
                print(f"⚠️ Output path targets system directory. Using default.")
                return "./test-output"
                
            return str(resolved_path)
            
        except Exception as e:
            print(f"⚠️ Error validating output path: {e}. Using default.")
            return "./test-output"
    
    @classmethod
    def validate_cache_size(cls, cache_file: str) -> bool:
        """Check if cache file size is within limits"""
        try:
            if os.path.exists(cache_file):
                size_mb = os.path.getsize(cache_file) / (1024 * 1024)
                if size_mb > cls.MAX_CACHE_SIZE_MB:
                    print(f"⚠️ Cache file too large ({size_mb:.1f}MB). Consider clearing cache.")
                    return False
            return True
        except Exception:
            return True  # If we can't check, assume it's okay


class RateLimiter:
    """with different limits for different request types"""
    
    def __init__(self, rate_limit: float, burst_limit: int = 50):
        self.rate_limit = SecurityConfig.validate_rate_limit(rate_limit)
        self.burst_limit = burst_limit  # Increased default
        self.last_requests = []
        self.last_request_time = 0
        
        # Separate tracking for different request types
        self.steam_api_requests = []  # For Steam API calls (more lenient)
        self.scraping_requests = []   # For web scraping (more restrictive)
        
        # Different limits for different request types
        self.steam_api_burst_limit = 100  # Higher limit for Steam API
        self.scraping_burst_limit = 20    # Lower limit for web scraping
        self.steam_api_window = 60        # 60 seconds for Steam API
        self.scraping_window = 60         # 60 seconds for scraping
        
    def wait_if_needed(self, request_type: str = "general"):
        """
        Enforce rate limiting with burst protection based on request type
        
        Args:
            request_type: "steam_api", "scraping", or "general"
        """
        current_time = time.time()
        
        if request_type == "steam_api":
            self._handle_steam_api_rate_limit(current_time)
        elif request_type == "scraping":
            self._handle_scraping_rate_limit(current_time)
        else:
            self._handle_general_rate_limit(current_time)
    
    def _handle_steam_api_rate_limit(self, current_time: float):
        """Handle rate limiting for Steam API requests (more lenient)"""
        # Clean old requests
        self.steam_api_requests = [t for t in self.steam_api_requests 
                                   if current_time - t < self.steam_api_window]
        
        # Check burst limit for Steam API (higher limit)
        if len(self.steam_api_requests) >= self.steam_api_burst_limit:
            sleep_time = self.steam_api_window - (current_time - self.steam_api_requests[0])
            if sleep_time > 0:
                print(f"🔄 Steam API burst limit reached. Waiting {sleep_time:.1f}s...")
                time.sleep(sleep_time)
                # Clean requests again after waiting
                current_time = time.time()
                self.steam_api_requests = [t for t in self.steam_api_requests 
                                          if current_time - t < self.steam_api_window]
        
        # Apply minimal rate limiting for Steam API (faster)
        time_since_last = current_time - self.last_request_time
        min_delay = max(0.1, self.rate_limit * 0.3)  # Much faster for Steam API
        if time_since_last < min_delay:
            sleep_time = min_delay - time_since_last
            time.sleep(sleep_time)
        
        # Record this request
        self.last_request_time = time.time()
        self.steam_api_requests.append(self.last_request_time)
    
    def _handle_scraping_rate_limit(self, current_time: float):
        """Handle rate limiting for web scraping (more restrictive)"""
        # Clean old requests
        self.scraping_requests = [t for t in self.scraping_requests 
                                  if current_time - t < self.scraping_window]
        
        # Check burst limit for scraping (lower limit)
        if len(self.scraping_requests) >= self.scraping_burst_limit:
            sleep_time = self.scraping_window - (current_time - self.scraping_requests[0])
            if sleep_time > 0:
                print(f"⚠️ Web scraping burst limit reached. Waiting {sleep_time:.1f}s...")
                time.sleep(sleep_time)
                # Clean requests again after waiting
                current_time = time.time()
                self.scraping_requests = [t for t in self.scraping_requests 
                                         if current_time - t < self.scraping_window]
        
        # Apply full rate limiting for web scraping
        time_since_last = current_time - self.last_request_time
        if time_since_last < self.rate_limit:
            sleep_time = self.rate_limit - time_since_last
            time.sleep(sleep_time)
        
        # Record this request
        self.last_request_time = time.time()
        self.scraping_requests.append(self.last_request_time)
    
    def _handle_general_rate_limit(self, current_time: float):
        """Handle general rate limiting (original behavior, but more lenient)"""
        # Remove requests older than burst window (60 seconds)
        self.last_requests = [t for t in self.last_requests if current_time - t < 60]
        
        # Check burst limit (now higher)
        if len(self.last_requests) >= self.burst_limit:
            sleep_time = 60 - (current_time - self.last_requests[0])
            if sleep_time > 0:
                print(f"⚠️ General burst limit reached. Waiting {sleep_time:.1f}s...")
                time.sleep(sleep_time)
        
        # Standard rate limiting
        time_since_last = current_time - self.last_request_time
        if time_since_last < self.rate_limit:
            sleep_time = self.rate_limit - time_since_last
            time.sleep(sleep_time)
        
        # Record this request
        self.last_request_time = time.time()
        self.last_requests.append(self.last_request_time)
    
    def get_stats(self) -> dict:
        """Get current rate limiting statistics"""
        current_time = time.time()
        
        # Clean old requests
        steam_api_recent = [t for t in self.steam_api_requests if current_time - t < 60]
        scraping_recent = [t for t in self.scraping_requests if current_time - t < 60]
        general_recent = [t for t in self.last_requests if current_time - t < 60]
        
        return {
            "steam_api_requests_last_minute": len(steam_api_recent),
            "scraping_requests_last_minute": len(scraping_recent),
            "general_requests_last_minute": len(general_recent),
            "steam_api_limit": self.steam_api_burst_limit,
            "scraping_limit": self.scraping_burst_limit,
            "general_limit": self.burst_limit
        }

class SecureRequestHandler:
    """Secure HTTP request handler with size limits and validation"""
    
    @staticmethod
    def make_secure_request(url: str, timeout: int = None, max_size_mb: float = None):
        """Make a secure HTTP request with size and safety checks"""
        import requests
        from urllib.parse import urlparse
        
        # Validate URL
        try:
            parsed = urlparse(url)
            if not parsed.scheme in ['http', 'https']:
                raise ValueError("Invalid URL scheme")
            if not parsed.netloc:
                raise ValueError("Invalid URL")
        except Exception as e:
            raise ValueError(f"Invalid URL: {e}")
        
        # Set secure defaults
        timeout = timeout or SecurityConfig.REQUEST_TIMEOUT
        max_size_mb = max_size_mb or SecurityConfig.MAX_REQUEST_SIZE_MB
        max_size_bytes = max_size_mb * 1024 * 1024
        
        # Configure session with security settings
        session = requests.Session()
        session.max_redirects = SecurityConfig.MAX_REDIRECTS
        
        # Add User-Agent to avoid being blocked
        headers = {
            'User-Agent': 'SlopScraper/1.0 (Educational/Research Tool)',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        }
        
        try:
            response = session.get(
                url, 
                timeout=timeout, 
                headers=headers,
                stream=True,  # Stream to check size
                allow_redirects=True
            )
            
            # Check response size before downloading
            content_length = response.headers.get('content-length')
            if content_length and int(content_length) > max_size_bytes:
                response.close()
                raise ValueError(f"Response too large: {content_length} bytes")
            
            # Download with size checking
            content = b''
            for chunk in response.iter_content(chunk_size=8192):
                content += chunk
                if len(content) > max_size_bytes:
                    response.close()
                    raise ValueError(f"Response exceeded size limit: {len(content)} bytes")
            
            # Set content for compatibility
            response._content = content
            return response
            
        except requests.exceptions.Timeout:
            raise TimeoutError("Request timed out")
        except requests.exceptions.TooManyRedirects:
            raise ValueError("Too many redirects")
        except Exception as e:
            raise Exception(f"Request failed: {e}")

class CredentialManager:
    """Secure credential management"""
    
    @staticmethod
    def validate_credentials(url: str, key: str) -> tuple[str, str]:
        """Validate Supabase credentials format"""
        if not url or not key:
            return None, None
            
        # Basic format validation
        if not url.startswith('https://'):
            print("⚠️ Supabase URL must use HTTPS")
            return None, None
            
        if 'supabase.co' not in url:
            print("⚠️ Invalid Supabase URL format")
            return None, None
            
        if len(key) < 50:  # Supabase keys are typically longer
            print("⚠️ Supabase key appears to be invalid length")
            return None, None
            
        return url, key
    
    @staticmethod
    def secure_credential_loading():
        """Load credentials with security validation"""
        # Try environment variables first (most secure)
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        
        if url and key:
            return CredentialManager.validate_credentials(url, key)
        
        # Fallback to file with warning
        creds_file = os.path.join(os.path.expanduser('~'), '.supabase_creds')
        if os.path.exists(creds_file):
            print("⚠️ Loading credentials from file. Environment variables are more secure.")
            try:
                # Check file permissions (Unix-like systems)
                if hasattr(os, 'stat'):
                    import stat
                    file_stat = os.stat(creds_file)
                    if file_stat.st_mode & (stat.S_IRGRP | stat.S_IROTH):
                        print("⚠️ Credentials file has overly permissive permissions!")
                
                with open(creds_file, 'r') as f:
                    import json
                    creds = json.load(f)
                    return CredentialManager.validate_credentials(
                        creds.get('url'), 
                        creds.get('key')
                    )
            except Exception as e:
                print(f"⚠️ Error loading credentials file: {e}")
        
        return None, None

# Session limits and monitoring
class SessionMonitor:
    """Monitor session activity for abuse detection"""
    
    def __init__(self):
        self.start_time = time.time()
        self.request_count = 0
        self.error_count = 0
        
    def record_request(self):
        """Record a request being made"""
        self.request_count += 1
        
        # Check for suspicious activity
        runtime = time.time() - self.start_time
        if runtime > 0 and self.request_count / runtime > 10:  # More than 10 req/sec average
            print("⚠️ High request rate detected. Consider increasing rate limit.")
    
    def record_error(self):
        """Record an error"""
        self.error_count += 1
        
        # If error rate is too high, something might be wrong
        if self.error_count > 20:
            print("⚠️ High error rate detected. Stopping for safety.")
            raise Exception("Too many errors - stopping execution")
    
    def check_runtime_limit(self):
        """Check if we've exceeded maximum runtime"""
        runtime_hours = (time.time() - self.start_time) / 3600
        if runtime_hours > SecurityConfig.MAX_EXECUTION_TIME_HOURS:
            print(f"⚠️ Maximum runtime ({SecurityConfig.MAX_EXECUTION_TIME_HOURS}h) exceeded")
            raise Exception("Runtime limit exceeded")

# Usage validation
def validate_usage_pattern():
    """Detect and prevent obvious abuse patterns"""
    # Check for rapid successive executions
    pid_file = "/tmp/slop_scraper.pid"
    try:
        if os.path.exists(pid_file):
            with open(pid_file, 'r') as f:
                last_run = float(f.read().strip())
                if time.time() - last_run < 30:  # Less than 30 seconds since last run
                    print("⚠️ Rapid successive executions detected. Please wait at least 1 minute between runs.")
                    return False
        
        # Write current timestamp
        with open(pid_file, 'w') as f:
            f.write(str(time.time()))
            
    except Exception:
        pass  # If we can't write pid file, continue anyway
    
    return True