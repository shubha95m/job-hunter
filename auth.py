"""
Interactive Authentication Script for Multi-Platform Job Hunting.
Supports manual login for LinkedIn and Naukri, saving session cookies locally.
"""

import sys
import argparse
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright
from browser import get_browser, get_context, save_state
from runtime.session_store import get_state_file

PLATFORM_LOGIN_CONFIGS = {
    "linkedin": {
        "name": "LinkedIn",
        "login_url": "https://www.linkedin.com/login",
        "state_key": "linkedin",
        "instructions": "Log in to your LinkedIn account. Once logged in, close the browser window.",
    },
    "naukri": {
        "name": "Naukri",
        "login_url": "https://www.naukri.com/nlogin/login",
        "state_key": "naukri",
        "instructions": "Log in to your Naukri account (via OTP, Google, or password). Once logged in, close the browser window.",
    },
}


async def manual_login(platform: str = "linkedin"):
    """Opens a headed browser for manual interactive login and exports session state."""
    config = PLATFORM_LOGIN_CONFIGS.get(platform.lower())
    if not config:
        print(f"Unknown platform '{platform}'. Supported platforms: {list(PLATFORM_LOGIN_CONFIGS.keys())}")
        return

    state_path = str(get_state_file(config["state_key"]))
    print(f"\n========================================================")
    print(f"  🔐 {config['name']} Manual Authentication")
    print(f"========================================================")
    print(f"Target URL : {config['login_url']}")
    print(f"State Path : {state_path}")
    print(f"\nInstructions: {config['instructions']}\n")

    async with async_playwright() as p:
        browser = await get_browser(p, headless=False)
        context = await get_context(browser, persist=False)  # Fresh context for authentication
        page = await context.new_page()

        await page.goto(config["login_url"])

        # Wait for user to close all open tabs / browser window after completing login
        try:
            while len(context.pages) > 0:
                await asyncio.sleep(0.5)
        except Exception:
            pass

        print(f"\n[Auth] Saving {config['name']} session state...")
        await save_state(context, state_file=state_path)
        try:
            await browser.close()
        except Exception:
            pass

        print(f"[Auth] ✅ {config['name']} session saved to '{state_path}'.")
        print(f"[Auth] You can now run autonomous workflows headlessly.\n")


def parse_args():
    parser = argparse.ArgumentParser(description="Authenticate with job platforms and save local session cookies.")
    parser.add_argument("--platform", choices=["linkedin", "naukri"], default=None, help="Target platform to authenticate with")
    parser.add_argument("--linkedin", action="store_true", help="Authenticate with LinkedIn (saves to .auth/state.json)")
    parser.add_argument("--naukri", action="store_true", help="Authenticate with Naukri (saves to .auth/naukri_state.json)")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    target_platform = "linkedin"
    if args.naukri:
        target_platform = "naukri"
    elif args.linkedin:
        target_platform = "linkedin"
    elif args.platform:
        target_platform = args.platform

    asyncio.run(manual_login(target_platform))
