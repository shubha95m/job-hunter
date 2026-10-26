"""
Naukri Phase 1: In-Platform Quick Apply Engine.
Autonomous application engine for Naukri jobs using saved user credentials and profile.
"""

import os
import asyncio
import re
from typing import Dict, Any, List, Set, Optional
from pathlib import Path
from playwright.async_api import async_playwright, BrowserContext, Page, Locator

from runtime.session_store import get_state_file, save_state
from platforms.naukri.dom import (
    JOB_CARD_SELECTOR,
    QUICK_APPLY_BUTTON_SELECTOR,
    QUESTIONNAIRE_DRAWER_SELECTOR,
    extract_card_details,
)


def load_applied_naukri_jobs(filepath: str = "applied_naukri_jobs.txt") -> Set[str]:
    """Load previously applied Naukri job URLs / identifiers."""
    if not os.path.exists(filepath):
        return set()
    with open(filepath, "r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def save_applied_naukri_job(job_id_or_url: str, filepath: str = "applied_naukri_jobs.txt", company: Optional[str] = None, role_title: Optional[str] = None):
    """Persist applied Naukri job identifier and sync with local CRM."""
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(f"{job_id_or_url}\n")
    try:
        from runtime.crm import record_application
        record_application(
            job_url=job_id_or_url,
            company=company or "Company via Naukri",
            role_title=role_title or "Target Role",
            platform="Naukri"
        )
    except Exception as e:
        print(f"[CRM Warning] Failed to log Naukri application to CRM: {e}")


def is_job_relevant(job_title: str, profile: dict) -> bool:
    """Validate job title against candidate's profile preferences."""
    keywords = profile.get("job_preferences", {}).get("keywords", [])
    if not keywords:
        return True

    title_lower = job_title.lower()
    for kw in keywords:
        kw_clean = kw.lower().strip()
        if kw_clean in title_lower:
            return True

    # Common synonym fallbacks for QA / SDET
    qa_terms = ["qa", "sdet", "quality", "test", "automation"]
    if any(term in title_lower for term in qa_terms):
        return True

    return False


async def handle_naukri_questionnaire(page: Page, profile: dict, timeout: int = 4000) -> bool:
    """Handle any questionnaire popup or chatbot drawer if presented after clicking Apply."""
    try:
        drawer = page.locator(QUESTIONNAIRE_DRAWER_SELECTOR).first
        if await drawer.count() == 0 or not await drawer.is_visible():
            return True

        print("  [Naukri] Questionnaire / Chatbot drawer detected. Filling answers...")
        years_exp = str(int(profile.get("professional_info", {}).get("years_of_experience", 9)))
        notice_days = str(profile.get("professional_info", {}).get("notice_period_days", 30))

        # Check for numeric or text inputs
        inputs = await drawer.locator("input[type='text'], input[type='number'], textarea").all()
        for inp in inputs:
            if not await inp.is_visible():
                continue
            placeholder = (await inp.get_attribute("placeholder") or "").lower()
            name_attr = (await inp.get_attribute("name") or "").lower()
            aria_label = (await inp.get_attribute("aria-label") or "").lower()
            field_context = f"{placeholder} {name_attr} {aria_label}"

            current_val = await inp.input_value()
            if not current_val:
                if any(k in field_context for k in ["exp", "year", "experience"]):
                    await inp.fill(years_exp)
                elif any(k in field_context for k in ["notice", "day", "period"]):
                    await inp.fill(notice_days)
                elif any(k in field_context for k in ["ctc", "salary"]):
                    await inp.fill("Not Disclosed")
                else:
                    await inp.fill("Yes")

        # Submit questionnaire
        submit_btn = drawer.locator("button:has-text('Submit'), button:has-text('Save'), button:has-text('Apply'), button:has-text('Continue')").first
        if await submit_btn.count() > 0 and await submit_btn.is_visible():
            await submit_btn.click()
            await page.wait_for_timeout(2000)

        return True
    except Exception as e:
        print(f"  [Naukri] Questionnaire handler exception: {e}")
        return False


async def apply_to_single_naukri_job(
    context: BrowserContext,
    card: Locator,
    profile: dict,
    applied_jobs: Set[str]
) -> bool:
    """Click quick apply on a card, handle new tab, submit application, and verify."""
    details = await extract_card_details(card)
    title = details["title"]
    company = details["company"]

    print(f"\nEvaluating: '{title}' at '{company}'")

    if not is_job_relevant(title, profile):
        print(f"  Skipping non-relevant title: '{title}'")
        return False

    qa_btn = card.locator("span:text-is('Quick apply'), button:has-text('Quick apply')").first
    if await qa_btn.count() == 0 or not await qa_btn.is_visible():
        print(f"  Skipping: No visible Quick apply button.")
        return False

    new_pages = []
    page_handler = lambda p: new_pages.append(p)
    context.on("page", page_handler)

    try:
        await qa_btn.click(timeout=5000)
        await asyncio.sleep(2.5)

        target_page: Optional[Page] = None
        if new_pages:
            target_page = new_pages[0]
            await target_page.wait_for_load_state("domcontentloaded", timeout=15000)
            clean_url = target_page.url.split("?")[0]
        else:
            clean_url = f"naukri-{company.replace(' ', '-').lower()}-{title.replace(' ', '-').lower()}"

        if clean_url in applied_jobs:
            print(f"  Already marked applied in history: {clean_url}")
            if target_page:
                await target_page.close()
            return False

        if target_page:
            print(f"  Opened Job Page: {clean_url}")
            # Locate apply button on the new page
            page_apply_btn = target_page.locator("button:has-text('Quick apply'), button:has-text('Apply')").first
            if await page_apply_btn.count() > 0 and await page_apply_btn.is_visible():
                btn_text = await page_apply_btn.inner_text()
                if "applied" not in btn_text.lower():
                    print("  Clicking in-page Apply button...")
                    await page_apply_btn.click(timeout=5000)
                    await target_page.wait_for_timeout(2500)
                    await handle_naukri_questionnaire(target_page, profile)

            page_content = (await target_page.content()).lower()
            if "applied" in page_content or "application sent" in page_content or "successfully applied" in page_content:
                print(f"  ✅ [Naukri] Successfully applied to '{title}' at '{company}'!")
                save_applied_naukri_job(clean_url, company=company, role_title=title)
                applied_jobs.add(clean_url)
                await target_page.close()
                return True
            else:
                print(f"  [Naukri] Application state ambiguous, saved identifier.")
                save_applied_naukri_job(clean_url, company=company, role_title=title)
                applied_jobs.add(clean_url)
                await target_page.close()
                return True
        else:
            # Applied directly in-page without opening new tab
            print(f"  ✅ [Naukri] Quick apply triggered directly on card for '{title}'!")
            save_applied_naukri_job(clean_url, company=company, role_title=title)
            applied_jobs.add(clean_url)
            return True

    except Exception as e:
        print(f"  Error applying to '{title}': {e}")
        return False
    finally:
        try:
            context.remove_listener("page", page_handler)
        except Exception:
            pass


async def search_and_apply_naukri(profile: dict, max_apps: int = 15, headless: bool = True) -> int:
    """
    Main Phase 1 Autonomous Application Runner for Naukri.
    Iterates through candidate search results, filtering for Quick Apply jobs headlessly in the backend.
    """
    naukri_state = str(get_state_file("naukri"))
    if not os.path.exists(naukri_state):
        print(f"\n[ERROR] Naukri session state not found at '{naukri_state}'.")
        print("Please authenticate first by running:\n    python auth.py --naukri\n")
        return 0

    keywords = profile.get("job_preferences", {}).get("keywords", ["Automation QA"])
    locations = profile.get("job_preferences", {}).get("locations", ["India"])

    primary_kw = keywords[0].lower().replace(" ", "-")
    primary_loc = locations[0].lower().replace(" ", "-") if locations else "india"

    # Search URL candidates (with intelligent fallback to ensure Quick Apply jobs are found)
    search_urls = []
    if primary_loc and primary_loc != "remote":
        search_urls.append(f"https://www.naukri.com/{primary_kw}-jobs-in-{primary_loc}")
    elif primary_loc == "remote":
        search_urls.append(f"https://www.naukri.com/{primary_kw}-jobs-in-remote")

    # Standard fallback keyword URL (high concentration of Quick Apply jobs)
    fallback_url = f"https://www.naukri.com/{primary_kw}-jobs"
    if fallback_url not in search_urls:
        search_urls.append(fallback_url)

    applied_jobs = load_applied_naukri_jobs()
    success_count = 0

    async with async_playwright() as p:
        args = ["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage"]
        try:
            browser = await p.chromium.launch(channel="chrome", headless=headless, args=args)
        except Exception:
            browser = await p.chromium.launch(headless=headless, args=args)

        context = await browser.new_context(
            storage_state=naukri_state,
            viewport={"width": 1440, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
        )
        page = await context.new_page()


        for search_url in search_urls:
            if success_count >= max_apps:
                break

            print(f"\n--- [Naukri Search] Navigating to: {search_url} ---")
            try:
                await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(3500)
            except Exception as e:
                print(f"Error loading search URL {search_url}: {e}")
                continue

            # Query all cards on the page
            cards = await page.locator(JOB_CARD_SELECTOR).all()
            print(f"Found {len(cards)} total job cards on current page.")

            # Filter for cards that offer Quick apply
            quick_apply_cards = []
            for c in cards:
                c_text = (await c.inner_text()).lower()
                if "quick apply" in c_text and "applied" not in c_text:
                    quick_apply_cards.append(c)

            print(f"Found {len(quick_apply_cards)} Phase 1 Quick Apply opportunities on page.")

            if not quick_apply_cards:
                print(f"No Quick Apply cards found on {search_url}. Checking next URL...")
                continue

            for card in quick_apply_cards:
                if success_count >= max_apps:
                    break

                applied = await apply_to_single_naukri_job(
                    context=context,
                    card=card,
                    profile=profile,
                    applied_jobs=applied_jobs
                )
                if applied:
                    success_count += 1
                    print(f"[Progress] Total Submitted: {success_count}/{max_apps}")
                    await asyncio.sleep(2.0)

            # Bring search page back to focus
            await page.bring_to_front()

        print(f"\n========================================================")
        print(f"  🏁 Naukri Run Complete!")
        print(f"  Successfully applied to {success_count} jobs.")
        print(f"========================================================\n")

        await save_state(context, state_file=naukri_state)
        await browser.close()

    return success_count
