"""
Single-file YouTube Cookie Manager using Playwright
==================================================

This module provides automatic YouTube authentication using Gmail credentials
and maintains fresh session cookies to bypass bot detection in yt-dlp.

Usage:
    from cookie_manager import start_cookie_refresh_loop, refresh_cookies
    
    # Start automatic 12-hour refresh loop
    start_cookie_refresh_loop()
    
    # Or manually refresh cookies
    refresh_cookies()

Environment Variables Required:
    YOUTUBE_EMAIL: Gmail email address
    YOUTUBE_PASSWORD: Gmail password (or App Password if 2FA enabled)
"""

import asyncio
import json
import os
import threading
import time
from typing import Dict, List, Optional
from datetime import datetime

try:
    from playwright.async_api import async_playwright, Browser, Page
except ImportError:
    print("⚠️ Playwright not installed. Run: pip install playwright")
    print("⚠️ Then install browser: playwright install chromium")
    raise

# Configuration
YOUTUBE_URL = "https://www.youtube.com"
GMAIL_LOGIN_URL = "https://accounts.google.com/signin"
COOKIES_FILE = "cookies.json"
LOGIN_TIMEOUT = 60  # seconds
REFRESH_INTERVAL = 12 * 60 * 60  # 12 hours in seconds

# Global variables
_refresh_thread = None
_stop_refresh = False


class YouTubeCookieManager:
    """Manages YouTube authentication and cookie persistence using Playwright."""
    
    def __init__(self):
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        
    async def __aenter__(self):
        """Async context manager entry."""
        await self.start_browser()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close_browser()
        
    async def start_browser(self) -> None:
        """Start headless Chromium browser."""
        try:
            playwright = await async_playwright().start()
            
            # Configure browser for headless mode with realistic settings
            self.browser = await playwright.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-blink-features=AutomationControlled',
                    '--disable-web-security',
                    '--disable-features=VizDisplayCompositor',
                    '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                ]
            )
            
            # Create new page with realistic viewport
            context = await self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            
            self.page = await context.new_page()
            
            # Set extra headers to appear more human-like
            await self.page.set_extra_http_headers({
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            })
            
        except Exception as e:
            print(f"⚠️ Failed to start browser: {e}")
            raise
            
    async def close_browser(self) -> None:
        """Close browser and cleanup resources."""
        try:
            if self.page:
                await self.page.close()
            if self.browser:
                await self.browser.close()
        except Exception as e:
            print(f"⚠️ Error closing browser: {e}")
            
    async def login_to_gmail(self, email: str, password: str) -> bool:
        """
        Perform Gmail login using credentials.
        
        Args:
            email: Gmail email address
            password: Gmail password
            
        Returns:
            bool: True if login successful, False otherwise
        """
        try:
            print(f"🔐 Logging into Gmail with {email}...")
            
            # Navigate to Gmail login page
            await self.page.goto(GMAIL_LOGIN_URL, wait_until='networkidle', timeout=LOGIN_TIMEOUT * 1000)
            
            # Wait for email input and enter email
            await self.page.wait_for_selector('input[type="email"]', timeout=LOGIN_TIMEOUT * 1000)
            await self.page.fill('input[type="email"]', email)
            
            # Click Next button
            await self.page.click('button:has-text("Next"), input[type="submit"]')
            
            # Wait for password input and enter password
            await self.page.wait_for_selector('input[type="password"]', timeout=LOGIN_TIMEOUT * 1000)
            await asyncio.sleep(2)  # Small delay to ensure page is ready
            await self.page.fill('input[type="password"]', password)
            
            # Click Next/Sign in button
            await self.page.click('button:has-text("Next"), button:has-text("Sign in"), input[type="submit"]')
            
            # Wait for login to complete - check for successful redirect or YouTube URL
            try:
                # Wait for either Google account page or direct redirect
                await self.page.wait_for_function(
                    "window.location.href.includes('myaccount.google.com') || "
                    "window.location.href.includes('youtube.com') || "
                    "document.querySelector('a[href*=\"youtube.com\"]') !== null",
                    timeout=LOGIN_TIMEOUT * 1000
                )
                print("✅ Gmail login successful")
                return True
                
            except Exception as wait_error:
                # Check if we're already logged in or if there's a 2FA challenge
                current_url = self.page.url
                page_content = await self.page.content()
                
                if "verify" in current_url.lower() or "challenge" in page_content.lower():
                    print("⚠️ 2FA verification required. Please use App Password instead of regular password.")
                    return False
                elif "youtube.com" in current_url or "myaccount.google.com" in current_url:
                    print("✅ Login successful (already authenticated)")
                    return True
                else:
                    print(f"⚠️ Login may have failed. Current URL: {current_url}")
                    return False
                    
        except Exception as e:
            print(f"⚠️ Gmail login failed: {e}")
            return False
            
    async def navigate_to_youtube(self) -> bool:
        """
        Navigate to YouTube and ensure we're logged in.
        
        Returns:
            bool: True if successfully on YouTube and logged in
        """
        try:
            print("🔄 Navigating to YouTube...")
            
            # Navigate to YouTube
            await self.page.goto(YOUTUBE_URL, wait_until='networkidle', timeout=LOGIN_TIMEOUT * 1000)
            
            # Wait a bit for the page to fully load
            await asyncio.sleep(3)
            
            # Check if we're logged in by looking for user avatar or account menu
            try:
                # Wait for signs that we're logged in
                await self.page.wait_for_selector(
                    'button[aria-label*="account"], button[aria-label*="Account"], img[alt*="Avatar"], yt-img-shadow img',
                    timeout=10000
                )
                print("✅ Successfully logged into YouTube")
                return True
                
            except Exception:
                # Alternative check - look for sign-in button (means we're not logged in)
                sign_in_button = await self.page.query_selector('a:has-text("Sign in"), button:has-text("Sign in")')
                if sign_in_button:
                    print("⚠️ Not logged into YouTube - found sign-in button")
                    return False
                else:
                    # If no sign-in button, assume we're logged in
                    print("✅ Appears to be logged into YouTube")
                    return True
                    
        except Exception as e:
            print(f"⚠️ Failed to navigate to YouTube: {e}")
            return False
            
    async def extract_and_save_cookies(self) -> bool:
        """
        Extract cookies from the browser session and save to file.
        
        Returns:
            bool: True if cookies saved successfully, False otherwise
        """
        try:
            print("🍪 Extracting cookies...")
            
            # Get all cookies from the current context
            cookies = await self.page.context.cookies()
            
            if not cookies:
                print("⚠️ No cookies found")
                return False
                
            # Filter YouTube-related cookies and convert to yt-dlp format
            youtube_cookies = []
            for cookie in cookies:
                # Include cookies from YouTube and Google domains
                if any(domain in cookie['domain'] for domain in ['.youtube.com', '.google.com', 'youtube.com', 'google.com']):
                    # Convert to Netscape cookie format for yt-dlp
                    youtube_cookies.append({
                        'name': cookie['name'],
                        'value': cookie['value'],
                        'domain': cookie['domain'],
                        'path': cookie.get('path', '/'),
                        'expires': cookie.get('expires', -1),
                        'httpOnly': cookie.get('httpOnly', False),
                        'secure': cookie.get('secure', False),
                        'sameSite': cookie.get('sameSite', 'no_restriction')
                    })
                    
            if not youtube_cookies:
                print("⚠️ No YouTube-related cookies found")
                return False
                
            # Save cookies to JSON file
            with open(COOKIES_FILE, 'w') as f:
                json.dump(youtube_cookies, f, indent=2)
                
            print(f"✅ Saved {len(youtube_cookies)} cookies to {COOKIES_FILE}")
            return True
            
        except Exception as e:
            print(f"⚠️ Failed to extract cookies: {e}")
            return False
            
    async def perform_login_and_save_cookies(self) -> bool:
        """
        Complete login process and save cookies.
        
        Returns:
            bool: True if entire process successful, False otherwise
        """
        try:
            # Get credentials from environment
            email = os.getenv('YOUTUBE_EMAIL')
            password = os.getenv('YOUTUBE_PASSWORD')
            
            if not email or not password:
                print("⚠️ Missing credentials: Set YOUTUBE_EMAIL and YOUTUBE_PASSWORD environment variables")
                return False
                
            # Perform Gmail login
            if not await self.login_to_gmail(email, password):
                return False
                
            # Navigate to YouTube
            if not await self.navigate_to_youtube():
                return False
                
            # Extract and save cookies
            return await self.extract_and_save_cookies()
            
        except Exception as e:
            print(f"⚠️ Login process failed: {e}")
            return False


async def refresh_cookies_async() -> bool:
    """
    Async function to refresh YouTube cookies.
    
    Returns:
        bool: True if refresh successful, False otherwise
    """
    try:
        async with YouTubeCookieManager() as manager:
            success = await manager.perform_login_and_save_cookies()
            if success:
                print("🔄 Cookies refreshed successfully")
            else:
                print("⚠️ Cookie refresh failed")
            return success
            
    except Exception as e:
        print(f"⚠️ Cookie refresh error: {e}")
        return False


def refresh_cookies() -> bool:
    """
    Synchronous wrapper to refresh YouTube cookies.
    
    Returns:
        bool: True if refresh successful, False otherwise
    """
    try:
        # Create new event loop for this thread if needed
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
        return loop.run_until_complete(refresh_cookies_async())
        
    except Exception as e:
        print(f"⚠️ Sync cookie refresh error: {e}")
        return False


def _refresh_loop():
    """Background thread function for automatic cookie refresh."""
    global _stop_refresh
    
    print(f"🔄 Starting automatic cookie refresh every {REFRESH_INTERVAL//3600} hours")
    
    # Initial refresh
    refresh_cookies()
    
    while not _stop_refresh:
        # Wait for the refresh interval, checking for stop signal every minute
        for _ in range(REFRESH_INTERVAL // 60):
            if _stop_refresh:
                break
            time.sleep(60)
            
        if not _stop_refresh:
            print("⏰ Time for scheduled cookie refresh...")
            refresh_cookies()
            
    print("🔄 Cookie refresh loop stopped")


def start_cookie_refresh_loop() -> None:
    """Start the automatic cookie refresh loop in a background thread."""
    global _refresh_thread, _stop_refresh
    
    if _refresh_thread and _refresh_thread.is_alive():
        print("🔄 Cookie refresh loop already running")
        return
        
    _stop_refresh = False
    _refresh_thread = threading.Thread(target=_refresh_loop, daemon=True)
    _refresh_thread.start()
    print("✅ Cookie refresh loop started")


def stop_cookie_refresh_loop() -> None:
    """Stop the automatic cookie refresh loop."""
    global _stop_refresh, _refresh_thread
    
    _stop_refresh = True
    if _refresh_thread:
        _refresh_thread.join(timeout=5)
        print("🛑 Cookie refresh loop stopped")


def check_cookies_file() -> bool:
    """
    Check if cookies file exists and is valid.
    
    Returns:
        bool: True if cookies file exists and contains data
    """
    try:
        if not os.path.exists(COOKIES_FILE):
            return False
            
        with open(COOKIES_FILE, 'r') as f:
            cookies = json.load(f)
            return len(cookies) > 0
            
    except Exception:
        return False


def get_cookies_for_ytdl() -> Dict:
    """
    Get yt-dlp configuration with cookies.
    
    Returns:
        dict: Configuration dict for yt-dlp with cookies
    """
    if check_cookies_file():
        return {'cookiefile': COOKIES_FILE}
    else:
        print("⚠️ No cookies file found. Run refresh_cookies() first.")
        return {}


# Convenience functions for immediate use
def ensure_cookies() -> bool:
    """
    Ensure cookies are available, refresh if needed.
    
    Returns:
        bool: True if cookies are available
    """
    if check_cookies_file():
        print("✅ Cookies file already exists")
        return True
    else:
        print("🔄 No cookies found, refreshing...")
        return refresh_cookies()


if __name__ == "__main__":
    """Test the cookie manager functionality."""
    print("🚀 Testing YouTube Cookie Manager")
    
    # Check for required environment variables
    if not os.getenv('YOUTUBE_EMAIL') or not os.getenv('YOUTUBE_PASSWORD'):
        print("⚠️ Please set YOUTUBE_EMAIL and YOUTUBE_PASSWORD environment variables")
        exit(1)
        
    # Test cookie refresh
    print("🔄 Testing cookie refresh...")
    success = refresh_cookies()
    
    if success:
        print("✅ Cookie manager test successful!")
        print(f"📁 Cookies saved to: {os.path.abspath(COOKIES_FILE)}")
        
        # Show how to use with yt-dlp
        print("\n📖 Usage with yt-dlp:")
        print("from cookie_manager import get_cookies_for_ytdl")
        print("import yt_dlp")
        print()
        print("ydl_opts = get_cookies_for_ytdl()")
        print("with yt_dlp.YoutubeDL(ydl_opts) as ydl:")
        print("    ydl.download(['https://www.youtube.com/watch?v=VIDEO_ID'])")
        
    else:
        print("❌ Cookie manager test failed!")
        exit(1)