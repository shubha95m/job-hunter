import asyncio
from playwright.async_api import async_playwright
from browser import get_browser, get_context, save_state

async def manual_login():
    """Opens a headed browser for the user to manually log in to LinkedIn."""
    print("Launching headed browser for manual login...")
    print("Please log in to LinkedIn. The session will be saved automatically.")
    print("Close the browser window when you are done.")
    
    async with async_playwright() as p:
        # We need a headed browser for manual login
        browser = await get_browser(p, headless=False)
        context = await get_context(browser, persist=False) # Start fresh
        page = await context.new_page()
        
        await page.goto("https://www.linkedin.com/login")
        
        # Wait for the user to close the browser
        try:
            await page.wait_for_event("close", timeout=0)
        except Exception as e:
            print(f"Browser closed.")
            
        print("Saving session state...")
        await save_state(context)
        await browser.close()
        print("Session saved successfully. You can now run the agent headlessly.")

if __name__ == "__main__":
    asyncio.run(manual_login())
