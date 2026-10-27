import os
import sys
import argparse
import asyncio
import yaml
import urllib.parse
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright, Page, BrowserContext
from dotenv import load_dotenv
from browser import get_browser, get_context, save_state
from agent import execute_smart_form_fill, get_easy_apply_modal
from external_portal_agent import execute_external_portal_apply
from llm_wrapper import token_tracker
from runtime.session_store import get_state_file

load_dotenv()

JOB_TIMEOUT_SECONDS = int(os.getenv("JOB_TIMEOUT_SECONDS", "240"))

def load_profile(profile_override: str = None):
    profile_name = profile_override or os.getenv("PROFILE", "dummy_profile")
    base_dir = Path(__file__).resolve().parent
    profile_path = str(base_dir / "profiles" / f"{profile_name}.yaml")
    if not os.path.exists(profile_path):
        profile_path = os.path.join("profiles", f"{profile_name}.yaml")
    if not os.path.exists(profile_path):
        print(f"ERROR: Profile not found at '{profile_path}'. Check your PROFILE setting in .env.")
        raise FileNotFoundError(profile_path)
    print(f"Loading profile: {profile_path}")
    with open(profile_path, "r") as f:
        data = yaml.safe_load(f) or {}

    # Allow overriding resume paths directly from .env if set
    env_resume = os.getenv("RESUME_PATH")
    if env_resume:
        data["resume_path"] = env_resume
    env_resume_1mb = os.getenv("RESUME_UNDER1MB_PATH")
    if env_resume_1mb:
        data["resume_under1mb_path"] = env_resume_1mb

    return data

def load_applied_jobs(filepath="applied_jobs.txt"):
    """Load previously applied jobs into a set."""
    if not os.path.exists(filepath):
        return set()
    with open(filepath, "r") as f:
        # Extract just the URL portion before the ' | ' if a timestamp exists
        return set(line.split(" | ")[0].strip() for line in f if line.strip())

def save_applied_job(job_url, filepath="applied_jobs.txt", company=None, role_title=None):
    """Append a successfully applied job to the tracking file and CRM database."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(filepath, "a") as f:
        f.write(f"{job_url} | {timestamp}\n")
    try:
        from runtime.crm import record_application
        record_application(
            job_url=job_url,
            company=company or "Company via LinkedIn",
            role_title=role_title or "Target Role",
            platform="LinkedIn",
            applied_at=timestamp
        )
    except Exception as e:
        print(f"[CRM Warning] Failed to log application to CRM: {e}")

def build_search_url(keywords, locations, easy_apply_only=False):
    base_url = "https://www.linkedin.com/jobs/search/?"
    keyword_str = urllib.parse.quote(" ".join(keywords))
    location_str = urllib.parse.quote(locations[0])
    
    # f_AL=true  = Easy Apply only
    params = (
        f"keywords={keyword_str}"
        f"&location={location_str}"
    )
    if easy_apply_only:
        params += "&f_AL=true"
    params += (
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

async def process_job(page: Page, job_url: str, profile: dict, context: BrowserContext = None, force: bool = False):
    print(f"\nProcessing job: {job_url}")
    await page.goto(job_url, wait_until="domcontentloaded")
    await asyncio.sleep(2)  # Give dynamic scripts / hydration a moment to attach
    
    # --- Relevance check: skip irrelevant jobs before doing anything ---
    try:
        job_title_el = page.locator("h1.t-24, h1.jobs-unified-top-card__job-title, .job-details-jobs-unified-top-card__job-title h1, h1[class*='job-title']").first
        job_title = (await job_title_el.inner_text()).strip() if await job_title_el.count() > 0 else ""
    except Exception:
        job_title = ""
    
    if not force and job_title and not is_job_relevant(job_title, profile):
        print(f"  Skipping irrelevant job: '{job_title}'")
        return False
    
    if job_title:
        print(f"  Job title: '{job_title}' — relevant, proceeding.")
    
    # --- Step 1: Wait for top-card buttons and sense whether Easy Apply, External Portal, or Already Applied ---
    try:
        try:
            await page.wait_for_selector(
                "button:has-text('Easy Apply'), [aria-label*='Easy Apply' i], [aria-label*='Apply on company website' i], a[href*='/safety/go/'], a:has-text('Apply'), button:has-text('Applied')",
                timeout=5000
            )
        except Exception:
            pass

        # Check if already applied on LinkedIn
        already_applied_loc = page.locator(
            "button:has-text('Applied'), "
            "[aria-label*='Applied' i], "
            ".jobs-s-apply__applied-update"
        ).first
        if await already_applied_loc.count() > 0 and await already_applied_loc.is_visible():
            print("  [Sense] Job is already marked as 'Applied' on LinkedIn.")
            return True

        # Strictly match Easy Apply buttons
        easy_apply_locator = page.locator(
            "button:has-text('Easy Apply'), "
            "[aria-label*='Easy Apply' i]"
        ).first
        
        is_easy_apply = await easy_apply_locator.is_visible()
        
        if is_easy_apply:
            print("  [Sense] Identified as LinkedIn Easy Apply job -> Routing to Phase 1 (In-Modal Agent)...")
            clicked = False
            for attempt in range(3):
                try:
                    await easy_apply_locator.click(timeout=5000)
                    clicked = True
                    break
                except Exception as click_err:
                    err_msg = str(click_err).lower()
                    if ("detached" in err_msg or "timeout" in err_msg) and attempt < 2:
                        print(f"  Easy Apply click retry {attempt + 1}/3 due to DOM change...")
                        await asyncio.sleep(1)
                        continue
                    raise click_err

            if not clicked:
                print("Could not click Easy Apply button.")
                return False
            
            modal = await get_easy_apply_modal(page, timeout=15000)
            if not await modal.is_visible():
                print("Easy Apply modal did not appear.")
                return False
            
            await asyncio.sleep(1.5)  # Wait for modal animation and footer buttons to mount

            # Phase 1: Smart Form Filling within LinkedIn modal
            print("Form opened. Handing over to Smart AI Agent (Phase 1).")
            success = await execute_smart_form_fill(page, profile)
            return success
        else:
            # Strictly match External Apply buttons (leading to company portals)
            external_apply_btn = page.locator(
                "[aria-label*='Apply on company website' i], "
                "a[href*='/safety/go/'], "
                "a[href*='/jobs/view/externalApply'], "
                "a:has-text('Apply'):not(:has-text('Easy Apply')), "
                "button:has-text('Apply'):not(:has-text('Easy Apply')), "
                "button:has-text('Apply on company website'), "
                "a:has-text('Apply on company website'), "
                "a[aria-label*='Apply' i]:not([aria-label*='Easy Apply' i]), "
                "button[aria-label*='Apply' i]:not([aria-label*='Easy Apply' i])"
            ).first

            is_external_apply = await external_apply_btn.is_visible()

            if is_external_apply:
                print("  [Sense] Identified as Company Portal job -> Routing to Phase 2 (External Portal Agent)...")
                external_page = None
                try:
                    if context:
                        async with context.expect_page(timeout=12000) as page_info:
                            await external_apply_btn.click(timeout=5000)
                        external_page = await page_info.value
                    else:
                        await external_apply_btn.click(timeout=5000)
                except Exception:
                    # Handle LinkedIn redirect confirmation modal if it appears
                    continue_btn = page.locator("button:has-text('Continue'), a:has-text('Continue')").first
                    if await continue_btn.is_visible() and context:
                        try:
                            async with context.expect_page(timeout=10000) as page_info:
                                await continue_btn.click(timeout=5000)
                            external_page = await page_info.value
                        except Exception:
                            pass


                if external_page:
                    print(f"  External portal tab opened: {external_page.url}")
                    try:
                        await external_page.wait_for_load_state("domcontentloaded", timeout=15000)
                        await asyncio.sleep(2)
                        # Phase 2: Full-Page External Portal Agent
                        success = await execute_external_portal_apply(external_page, profile, job_title)
                        return success
                    finally:
                        try:
                            await external_page.close()
                        except Exception:
                            pass
                else:
                    print("Could not open or capture external company portal page.")
                    return False
            else:
                print("  [Sense] No apply button available on this job (expired, already applied, or not accepting applications).")
                return False

    except Exception as e:
        print(f"Error or timeout finding Apply button: {e}")
        return False


async def has_valid_linkedin_session(page: Page) -> bool:
    """Detect expired auth before starting the job loop."""
    url = page.url.lower()
    if "/login" in url or "checkpoint" in url:
        return False

    login_indicators = page.locator("input[name='session_key'], input[name='session_password'], text=/sign in/i")
    try:
        return not await login_indicators.first.is_visible(timeout=2500)
    except Exception:
        return True

async def dismiss_easy_apply_modal(page: Page):
    """Best-effort cleanup so one failed application does not block the next job."""
    try:
        discard_selectors = (
            "button:has-text('Discard'), "
            "[data-testid='dialog'] button:has-text('Discard'), "
            "button[data-control-name*='discard'], "
            "button[data-test-dialog-secondary-action]"
        )

        # 1. If 'Save this application?' popup is already open, click Discard immediately
        discard_btn = page.locator(discard_selectors).first
        if await discard_btn.count() > 0 and await discard_btn.is_visible():
            await discard_btn.click(timeout=3000)
            await asyncio.sleep(1)
            return

        # 2. Otherwise click Dismiss (X)
        dismiss_btn = page.locator(
            "dialog[open] button[aria-label='Dismiss'], "
            "dialog[open] button:has-text('Dismiss'), "
            "[data-testid='dialog'] button[aria-label='Dismiss'], "
            "[data-testid='dialog'] button:has-text('Dismiss'), "
            "[role='dialog'] button[aria-label='Dismiss'], "
            ".artdeco-modal button[aria-label='Dismiss'], "
            "button[aria-label='Dismiss']"
        ).first
        if await dismiss_btn.count() > 0 and await dismiss_btn.is_visible():
            await dismiss_btn.click(timeout=3000)
            await asyncio.sleep(1)

        # 3. Handle the 'Save this application?' confirmation popup
        discard_btn = page.locator(discard_selectors).first
        try:
            await discard_btn.wait_for(state="visible", timeout=3000)
            await discard_btn.click(timeout=3000)
            await asyncio.sleep(0.5)
        except Exception:
            pass
    except Exception:
        pass


async def run_linkedin_workflow(profile: dict, max_apps: int = 15, headless: bool = False):
    """Executes the LinkedIn Job Hunter application workflow (Phase 1 Easy Apply & Phase 2 ATS Portals)."""
    print("\n--- [LinkedIn Engine] Starting Application Run ---")
    keywords = profile.get("job_preferences", {}).get("keywords", [])
    locations = profile.get("job_preferences", {}).get("locations", [])
    
    if not keywords or not locations:
        print("Error: Keywords and locations must be defined in profile.")
        return

    easy_apply_only = profile.get("job_preferences", {}).get("easy_apply_only", False)
    search_url = build_search_url(keywords, locations, easy_apply_only=easy_apply_only)
    print(f"Search URL: {search_url} (Easy Apply Only: {easy_apply_only})")
    
    async with async_playwright() as p:
        browser = await get_browser(p, headless=headless)
        context = await get_context(browser, persist=True)
        page = await context.new_page()
        
        print("Navigating to LinkedIn search results...")
        await page.goto(search_url, wait_until="domcontentloaded")
        await page.wait_for_load_state("domcontentloaded")

        if not await has_valid_linkedin_session(page):
            print("ERROR: LinkedIn session is not valid. Run `python auth.py --linkedin` and log in again.")
            await browser.close()
            return
        
        # Scrape job cards (robust method)
        job_links = []
        try:
            await page.wait_for_selector(".jobs-search-results__list, .scaffold-layout__list", timeout=15000)
            target_links = max(max_apps * 5, max_apps)
            print(f"Scrolling job list to collect up to {target_links} candidate job links...")
            for scroll_pass in range(10):
                links = await page.locator("a[href*='/jobs/view/']").all()
                for link in links:
                    href = await link.get_attribute("href")
                    if href:
                        clean_url = "https://www.linkedin.com" + href.split("?")[0] if href.startswith("/") else href.split("?")[0]
                        if clean_url not in job_links:
                            job_links.append(clean_url)
                
                if len(job_links) >= target_links:
                    break
                
                await page.evaluate("""
                    const list = document.querySelector('.jobs-search-results__list, .scaffold-layout__list');
                    if (list) list.scrollBy(0, 600);
                """)
                await asyncio.sleep(1.5)
            
            print(f"Found {len(job_links)} unique job links after scrolling.")
        except Exception as e:
            print(f"Error scraping job list: {e}")
            
        print(f"Found {len(job_links)} jobs to process.")
        
        applied_jobs_set = load_applied_jobs(filepath="applied_jobs.txt")
        success_count = 0
        successful_jobs = []

        for link in job_links:
            if success_count >= max_apps:
                print(f"\n[INFO] Reached maximum requested applications ({max_apps}). Stopping.")
                break
                
            if not link.startswith("http"):
                continue
                
            clean_link = link.split('?')[0]
            if clean_link in applied_jobs_set:
                print(f"Skipping already applied job: {clean_link}")
                continue
                
            success = False
            try:
                success = await asyncio.wait_for(
                    process_job(page, link, profile, context=context),
                    timeout=JOB_TIMEOUT_SECONDS,
                )

                if not success:
                    await dismiss_easy_apply_modal(page)
            except asyncio.TimeoutError:
                print(f"Timed out processing job after {JOB_TIMEOUT_SECONDS}s: {link}")
                await dismiss_easy_apply_modal(page)
            except Exception as e:
                print(f"Error processing job {link}: {e}")
                await dismiss_easy_apply_modal(page)
            if success:
                success_count += 1
                successful_jobs.append(link)
                save_applied_job(clean_link, filepath="applied_jobs.txt")
                applied_jobs_set.add(clean_link)
                
            await asyncio.sleep(2)
            
        print("\n=================================")
        print(f"LinkedIn Job Hunter Run Complete!")
        print(f"Total Successfully Applied: {success_count}")
        for job in successful_jobs:
            print(f" - {job}")
        print("=================================\n")

        token_tracker.print_summary()
        await save_state(context)
        await browser.close()


async def run_naukri_workflow(profile: dict, max_apps: int = 15, headless: bool = True):
    """Executes the Naukri Job Hunter Phase 1 application workflow headlessly in the background."""
    from platforms.naukri.quick_apply import search_and_apply_naukri
    await search_and_apply_naukri(profile=profile, max_apps=max_apps, headless=headless)



async def run_wishlist_workflow(profile: dict, headless: bool = True):
    """Executes applications for all saved jobs in your local Wishlist queue."""
    from runtime.crm import get_wishlist
    wishlist = get_wishlist()
    if not wishlist:
        print("Your Wishlist is currently empty.")
        return

    print(f"\n--- [Wishlist Runner] Processing {len(wishlist)} Saved Opportunity(ies) ---")
    async with async_playwright() as p:
        browser = await get_browser(p, headless=headless)
        context = await get_context(browser, persist=True)
        page = await context.new_page()

        for item in wishlist:
            url = item["job_url"]
            comp = item["company"]
            role = item["role_title"]
            platform = item.get("platform", "LinkedIn").lower()

            print(f"\nProcessing Wishlist Job: {role} at {comp} [{item.get('platform')}]")
            if "linkedin" in platform:
                try:
                    success = await process_job(page, url, profile, context=context, force=True)
                    if success:
                        save_applied_job(url, company=comp, role_title=role)
                        print(f"  ✅ Successfully applied to {role} at {comp}!")
                    else:
                        print(f"  Could not complete application for {role} at {comp}.")
                except Exception as e:
                    print(f"  Error applying to {url}: {e}")
            else:
                print(f"  Skipping non-LinkedIn platform '{item.get('platform')}' in this automated batch.")

        await browser.close()


def parse_args():
    parser = argparse.ArgumentParser(description="Autonomous Multi-Platform Job Hunter & Application Agent")
    parser.add_argument("--platform", choices=["linkedin", "naukri"], default=None, help="Target platform to run")
    parser.add_argument("--linkedin", action="store_true", help="Run LinkedIn job applications")
    parser.add_argument("--naukri", action="store_true", help="Run Naukri job applications")
    parser.add_argument("--wishlist", action="store_true", help="Apply to all saved jobs in your Wishlist queue")
    parser.add_argument("--profile", type=str, default=None, help="Candidate profile name in profiles/")
    parser.add_argument("--max-apps", type=int, default=None, help="Maximum number of applications to submit")
    parser.add_argument("--headed", action="store_true", help="Run browser in visible headed mode (default: False, runs headless)")
    parser.add_argument("--headless", action="store_true", default=True, help="Run browser in headless mode (default: True)")
    return parser.parse_args()


async def main():
    args = parse_args()
    
    # Resolve platform
    target_platform = "linkedin"
    if args.naukri:
        target_platform = "naukri"
    elif args.linkedin:
        target_platform = "linkedin"
    elif args.platform:
        target_platform = args.platform

    profile = load_profile(profile_override=args.profile)
    max_apps = args.max_apps or int(os.getenv("MAX_APPLICATIONS", "15"))
    headless = not args.headed if args.headed else (os.getenv("HEADLESS", "true").lower() == "true")

    print(f"\n========================================================")
    print(f"  🤖 Autonomous Job Hunter Engine")
    if args.wishlist:
        print(f"  Mode            : WISHLIST QUEUE RUNNER")
    else:
        print(f"  Target Platform : {target_platform.upper()}")
        print(f"  Max Applications: {max_apps}")
    print(f"  Headless Mode   : {headless}")
    print(f"========================================================\n")

    if args.wishlist:
        await run_wishlist_workflow(profile=profile, headless=headless)
    elif target_platform == "naukri":
        await run_naukri_workflow(profile=profile, max_apps=max_apps, headless=headless)
    else:
        await run_linkedin_workflow(profile=profile, max_apps=max_apps, headless=headless)


if __name__ == "__main__":
    asyncio.run(main())
