"""
Shared DOM and UI Utilities for Playwright.
Deduplicates spinner waits, robust clicking, and field heuristics across Phase 1 and Phase 2 agents.
"""

import asyncio
from playwright.async_api import Page, Locator


async def wait_for_spinners_and_loaders(page: Page, timeout_seconds: float = 6.0):
    """Wait for enterprise loading spinners, skeletons, and animation overlays to disappear."""
    spinner_selectors = [
        "[data-automation-id*='loading' i]",
        "[data-automation-id*='spinner' i]",
        ".loading-spinner",
        ".artdeco-loader",
        ".artdeco-spinner",
        "[aria-busy='true']",
        ".workday-loader",
    ]
    for sel in spinner_selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                await loc.wait_for(state="hidden", timeout=int(timeout_seconds * 1000))
        except Exception:
            pass


async def resilient_click(locator: Locator, max_retries: int = 3, timeout_ms: int = 4000) -> bool:
    """Click a locator with retries and force-click fallback."""
    for attempt in range(max_retries):
        try:
            await locator.scroll_into_view_if_needed(timeout=timeout_ms)
            await locator.click(timeout=timeout_ms)
            return True
        except Exception:
            if attempt == max_retries - 1:
                try:
                    await locator.click(force=True, timeout=timeout_ms)
                    return True
                except Exception:
                    return False
            await asyncio.sleep(0.5)
    return False


async def get_clean_text(locator: Locator) -> str:
    """Extract trimmed inner text from locator safely."""
    try:
        return (await locator.inner_text()).strip()
    except Exception:
        return ""
