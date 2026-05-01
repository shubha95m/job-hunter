import os
from playwright.async_api import async_playwright, Browser, BrowserContext, Playwright

AUTH_DIR = ".auth"
STATE_FILE = os.path.join(AUTH_DIR, "state.json")

async def get_browser(p: Playwright, headless: bool = True) -> Browser:
    """Launch the browser."""
    # Using chromium
    browser = await p.chromium.launch(
        headless=headless,
        args=["--start-maximized", "--disable-blink-features=AutomationControlled"]
    )
    return browser

async def get_context(browser: Browser, persist: bool = True) -> BrowserContext:
    """Get a browser context, loading saved state if available and persistent."""
    if not os.path.exists(AUTH_DIR):
        os.makedirs(AUTH_DIR, exist_ok=True)
        
    context_args = {
        "viewport": {"width": 1920, "height": 1080},
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    if persist and os.path.exists(STATE_FILE):
        context = await browser.new_context(storage_state=STATE_FILE, **context_args)
    else:
        context = await browser.new_context(**context_args)
        
    return context

async def save_state(context: BrowserContext):
    """Save the current context state (cookies, local storage)."""
    if not os.path.exists(AUTH_DIR):
        os.makedirs(AUTH_DIR, exist_ok=True)
    await context.storage_state(path=STATE_FILE)
