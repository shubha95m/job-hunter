import os
import asyncio
import yaml
import urllib.parse
from datetime import datetime
from playwright.async_api import async_playwright, Page
from browser import get_browser, get_context
from agent import execute_smart_form_fill

def load_profile():
    profile_name = os.getenv("PROFILE", "shubham_profile")
    profile_path = os.path.join("profiles", f"{profile_name}.yaml")
    if not os.path.exists(profile_path):
        print(f"ERROR: Profile not found at '{profile_path}'. Check your PROFILE setting in .env.")
        raise FileNotFoundError(profile_path)
    print(f"Loading profile: {profile_path}")
    with open(profile_path, "r") as f:
        return yaml.safe_load(f)

def load_applied_jobs(filepath="applied_jobs.txt"):
    """Load previously applied jobs into a set."""
    if not os.path.exists(filepath):
        return set()
    with open(filepath, "r") as f:
        # Extract just the URL portion before the ' | ' if a timestamp exists
        return set(line.split(" | ")[0].strip() for line in f if line.strip())

def save_applied_job(job_url, filepath="applied_jobs.txt"):
    """Append a successfully applied job to the tracking file."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(filepath, "a") as f:
        f.write(f"{job_url} | {timestamp}\n")

def build_search_url(keywords, locations):
    base_url = "https://www.linkedin.com/jobs/search/?"
    keyword_str = urllib.parse.quote(" ".join(keywords))
    location_str = urllib.parse.quote(locations[0])
    
    # f_AL=true  = Easy Apply only
    # f_I=96,4,556 = IT Services & Consulting, Software Development, Technology & Information
    # f_CF=f_AL  = Combined filter: Easy Apply within the IT category
    params = (
        f"keywords={keyword_str}"
        f"&location={location_str}"
        f"&f_AL=true"
        f"&f_I=96%2C4%2C556%2C6"   # IT Services, Software Dev, Tech & Info, Computer Hardware
        f"&f_WT=2%2C3%2C4"          # Work type: Remote (2), Hybrid (3), On-site (4) — keeps all
    )
    return base_url + params

def is_job_relevant(job_title: str, profile: dict) -> bool:
    """
    Checks if a job title contains at least one keyword from the profile.
    Case-insensitive. Returns True even for contract/freelance roles.
    """
    keywords = profile.get("job_preferences", {}).get("keywords", [])
    title_lower = job_title.lower()
    
    # Strip common contract/freelance qualifiers so they don't block matching
    for noise in ["(contract)", "(freelance)", "(part-time)", "(hourly)", "- contract", "- freelance"]:
        title_lower = title_lower.replace(noise, "")
    
    return any(kw.lower() in title_lower for kw in keywords)

async def process_job(page: Page, job_url: str, profile: dict):
    print(f"\nProcessing job: {job_url}")
    await page.goto(job_url)
    await page.wait_for_load_state("domcontentloaded")
    await asyncio.sleep(2) # Give dynamic scripts a moment to attach
    
    # --- Relevance check: skip irrelevant jobs before doing anything ---
    try:
        job_title_el = page.locator("h1.t-24, h1.jobs-unified-top-card__job-title, .job-details-jobs-unified-top-card__job-title h1").first
        job_title = (await job_title_el.inner_text()).strip() if await job_title_el.count() > 0 else ""
    except Exception:
        job_title = ""
    
    if job_title and not is_job_relevant(job_title, profile):
        print(f"  Skipping irrelevant job: '{job_title}'")
        return False
    
    if job_title:
        print(f"  Job title: '{job_title}' — relevant, proceeding.")
    
    # Check for Easy Apply button
    try:
        easy_apply_element = page.locator("text='Easy Apply'").first
        await easy_apply_element.wait_for(state="visible", timeout=5000)
        
        if await easy_apply_element.is_visible():
            print("Found Easy Apply button. Clicking...")
            await easy_apply_element.click()
            
            # AI Agent takes over here
            print("Form opened. Handing over to Smart AI Agent.")
            success = await execute_smart_form_fill(page, profile)
            return success
        else:
            print("No Easy Apply button found on this job.")
            return False
    except Exception as e:
        print(f"Error or timeout finding Easy Apply button: {e}")
        return False

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
        max_apps = int(os.getenv("MAX_APPLICATIONS", "15"))
        try:
            # Wait for the job list to appear
            await page.wait_for_selector(".jobs-search-results__list, .scaffold-layout__list", timeout=15000)
            
            # Scroll the job list panel to lazy-load more cards
            print(f"Scrolling job list to collect up to {max_apps} job links...")
            for scroll_pass in range(10): # scroll up to 10 times
                # Collect current links
                links = await page.locator("a[href*='/jobs/view/']").all()
                for link in links:
                    href = await link.get_attribute("href")
                    if href:
                        clean_url = "https://www.linkedin.com" + href.split("?")[0] if href.startswith("/") else href.split("?")[0]
                        if clean_url not in job_links:
                            job_links.append(clean_url)
                
                if len(job_links) >= max_apps:
                    break # We have enough, stop scrolling
                
                # Scroll the job list panel down to load more cards
                await page.evaluate("""
                    const list = document.querySelector('.jobs-search-results__list, .scaffold-layout__list');
                    if (list) list.scrollBy(0, 600);
                """)
                await asyncio.sleep(1.5) # wait for new cards to load
            
            print(f"Found {len(job_links)} unique job links after scrolling.")
            # We no longer hardcode a limit here, we check max_applications below
        except Exception as e:
            print(f"Error scraping job list: {e}")
            
        print(f"Found {len(job_links)} jobs to process.")
        
        applied_jobs_set = load_applied_jobs()
        success_count = 0
        successful_jobs = []
        

        for link in job_links:
            if success_count >= max_apps:
                print(f"\\n[INFO] Reached maximum requested applications ({max_apps}). Stopping.")
                break
                
            if not link.startswith("http"):
                continue
                
            # Normalize the link to avoid query param mismatches
            clean_link = link.split('?')[0]
            if clean_link in applied_jobs_set:
                print(f"Skipping already applied job: {clean_link}")
                continue
                
            success = await process_job(page, link, profile)
            if success:
                success_count += 1
                successful_jobs.append(link)
                save_applied_job(clean_link)
                applied_jobs_set.add(clean_link)
                
            # Add human-like delay
            await asyncio.sleep(2)
            
        print("\n=================================")
        print(f"Job Hunter Run Complete!")
        print(f"Total Successfully Applied: {success_count}")
        for job in successful_jobs:
            print(f" - {job}")
        print("=================================\n")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
