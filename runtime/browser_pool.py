"""
High-Performance Playwright Browser Context Pool.
Provides lazy-initialized, self-recycling browser sessions to prevent memory leaks
and avoid Chromium launch overhead across sequential MCP tool invocations.
"""

import asyncio
from typing import Optional, AsyncGenerator
from contextlib import asynccontextmanager
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright
from runtime.session_store import get_state_file


class BrowserContextPool:
    """
    Manages Playwright browser lifecycle with auto-recycle.
    Reuses browser instances across calls, cycling context after MAX_USES to prevent DOM leaks.
    """
    MAX_USES = 20

    def __init__(self):
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._lock = asyncio.Lock()
        self._use_count = 0

    async def _ensure_browser(self, headless: bool = True) -> Browser:
        if self._browser is None or not self._browser.is_connected():
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=headless,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ]
            )
            self._use_count = 0
        return self._browser

    @asynccontextmanager
    async def page(self, platform: str = "linkedin", headless: bool = True) -> AsyncGenerator[Page, None]:
        """
        Lease an authenticated Page for a single task.
        Recycles context automatically upon completion.
        """
        async with self._lock:
            browser = await self._ensure_browser(headless=headless)
            state_file = get_state_file(platform)
            
            context_kwargs = {}
            if state_file.exists():
                context_kwargs["storage_state"] = str(state_file)
                
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
                **context_kwargs
            )
            page = await context.new_page()
            self._use_count += 1

        try:
            yield page
        finally:
            try:
                await page.close()
                await context.close()
            except Exception:
                pass

            # Recycle browser after MAX_USES to prevent Chromium memory bloat
            if self._use_count >= self.MAX_USES:
                await self.close()

    async def close(self):
        """Cleanly terminate the pooled browser and playwright runtime."""
        async with self._lock:
            if self._browser:
                try:
                    await self._browser.close()
                except Exception:
                    pass
                self._browser = None
            if self._playwright:
                try:
                    await self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None
            self._use_count = 0


# Global shared pool singleton
browser_pool = BrowserContextPool()
