import asyncio
import yaml
import urllib.parse
from playwright.async_api import async_playwright, Page
from browser import get_browser, get_context

def load_profile(path="profile_template.yaml"):
    with open(path, "r") as f:
        return yaml.safe_load(f)

def build_search_url(keywords, locations):
    # This is a simplified LinkedIn jobs search URL construction
    base_url = "https://www.linkedin.com/jobs/search/?"
    keyword_str = urllib.parse.quote(" ".join(keywords))
    location_str = urllib.parse.quote(locations[0]) # Start with first location
    
    # f_AL=true means Easy Apply only
    params = f"keywords={keyword_str}&location={location_str}&f_AL=true"
    return base_url + params

async def process_job(page: Page, job_url: str, profile: dict):
    print(f"\nProcessing job: {job_url}")
    await page.goto(job_url)
    await page.wait_for_load_state("domcontentloaded")
    await asyncio.sleep(2) # Give dynamic scripts a moment to attach
    
    # Check for easy apply button
    try:
        # Wait a bit for dynamic content to load
        easy_apply_button = page.locator(".jobs-apply-button, button:has-text('Easy Apply'), button:has-text('Apply')").filter(has_text="Apply").first
        await easy_apply_button.wait_for(state="visible", timeout=5000)
        
        if await easy_apply_button.is_visible():
            print("Found Easy Apply button. Clicking...")
            await easy_apply_button.click()
            
            # TODO: Implement form traversal logic here
            print("Form opened. Handing over to LLM/Form filler (placeholder).")
            # Close the modal for now since we are just scaffolding
            close_btn = page.locator("button[aria-label='Dismiss']")
            if await close_btn.is_visible():
               await close_btn.click()
               discard_btn = page.locator("button[data-control-name='discard_application_confirm_btn']")
               if await discard_btn.is_visible():
                   await discard_btn.click()
        else:
            print("No Easy Apply button found on this job.")
    except Exception as e:
        print(f"Error or timeout finding Easy Apply button: {e}")

async def main():
    print("Starting Job Hunter...")
    profile = load_profile()
    keywords = profile.get("job_preferences", {}).get("keywords", [])
    locations = profile.get("job_preferences", {}).get("locations", [])
    
    if not keywords or not locations:
        print("Error: Keywords and locations must be defined in profile.")
        return

    search_url = build_search_url(keywords, locations)
    print(f"Search URL: {search_url}")
    
    async with async_playwright() as p:
        browser = await get_browser(p, headless=False)
        # Attempt to load persistent context. Ensure user has run auth.py first!
        context = await get_context(browser, persist=True)
        page = await context.new_page()
        
        print("Navigating to search results...")
        await page.goto(search_url)
        await page.wait_for_load_state("domcontentloaded")
        
        # Scrape job cards (robust method)
        job_links = []
        try:
            # Wait a few seconds for the React app to render the job list
            await asyncio.sleep(5) 
            
            # Find all links that point to a job posting
            links = await page.locator("a[href*='/jobs/view/']").all()
            for link in links:
                href = await link.get_attribute("href")
                if href:
                    # Clean up the URL and handle relative vs absolute paths
                    clean_url = "https://www.linkedin.com" + href.split("?")[0] if href.startswith("/") else href.split("?")[0]
                    if clean_url not in job_links:
                        job_links.append(clean_url)
                        
            # Limit to top 3 for testing
            job_links = job_links[:3]
        except Exception as e:
            print(f"Error scraping job list: {e}")
            
        print(f"Found {len(job_links)} jobs to process.")
        
        for link in job_links:
            if not link.startswith("http"):
                continue
            await process_job(page, link, profile)
            # Add human-like delay
            await asyncio.sleep(2)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
