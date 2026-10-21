import os
from typing import Optional
from playwright.async_api import Browser, BrowserContext, Playwright

AUTH_DIR = ".auth"
STATE_FILE = os.path.join(AUTH_DIR, "state.json")

async def get_browser(p: Playwright, headless: bool = True) -> Browser:
    """Launch the browser headlessly with real Chrome engine to bypass anti-bot detections."""
    args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage"
    ]
    try:
        return await p.chromium.launch(
            channel="chrome",
            headless=headless,
            args=args
        )
    except Exception:
        return await p.chromium.launch(
            headless=headless,
            args=args
        )

async def get_context(browser: Browser, persist: bool = True, state_file: Optional[str] = None) -> BrowserContext:
    """Get a browser context, loading saved state if available and persistent."""
    target_state = state_file or STATE_FILE
    if not os.path.exists(AUTH_DIR):
        os.makedirs(AUTH_DIR, exist_ok=True)
        
    context_args = {
        "viewport": {"width": 1440, "height": 900},
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
    }

    if persist and os.path.exists(target_state):
        context = await browser.new_context(storage_state=target_state, **context_args)
    else:
        context = await browser.new_context(**context_args)
        
    return context

async def save_state(context: BrowserContext, state_file: Optional[str] = None):
    """Save the current context state (cookies, local storage)."""
    target_state = state_file or STATE_FILE
    target_dir = os.path.dirname(target_state) or AUTH_DIR
    if not os.path.exists(target_dir):
        os.makedirs(target_dir, exist_ok=True)
    await context.storage_state(path=target_state)
