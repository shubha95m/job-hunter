"""
Naukri Platform API Module.
Interface for Naukri recruiter discovery, live profile intelligence, and job search.
Runs 100% headless in the background via modern Chrome engine.
"""

import os
import re
import json
import asyncio
from typing import Dict, Any, List, Optional
from pathlib import Path
from playwright.async_api import async_playwright, Playwright, Browser

from runtime.session_store import get_state_file
from platforms.naukri.dom import JOB_CARD_SELECTOR, extract_card_details


async def _launch_headless_browser(p: Playwright) -> Browser:
    """Launch headless browser using real Chrome channel to prevent UI popups and bypass bot detection."""
    args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage"
    ]
    try:
        return await p.chromium.launch(channel="chrome", headless=True, args=args)
    except Exception:
        return await p.chromium.launch(headless=True, args=args)


class NaukriAPIClient:
    """Naukri Gateway client for high-speed job and recruiter operations."""

    def __init__(self):
        self.platform_name = "naukri"
        self.state_file = str(get_state_file("naukri"))
        self.user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"

    async def get_profile(self, live: bool = True) -> Dict[str, Any]:
        """Fetch candidate profile from Naukri (live headless DOM extraction with session fallback)."""
        if not os.path.exists(self.state_file):
            return {
                "platform": "naukri",
                "status": "UNAUTHENTICATED",
                "message": "Naukri session state not found. Run 'python auth.py --naukri' first."
            }

        if not live:
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    state_data = json.load(f)
                cookies = state_data.get("cookies", [])
                return {
                    "platform": "naukri",
                    "status": "AUTHENTICATED",
                    "cookies_count": len(cookies),
                    "state_file": self.state_file,
                    "message": "Naukri active session verified."
                }
            except Exception as e:
                return {"platform": "naukri", "status": "ERROR", "error": str(e)}

        # Fetch live profile data from Naukri TopTier / candidate profile page headlessly
        async with async_playwright() as p:
            browser = await _launch_headless_browser(p)
            context = await browser.new_context(
                storage_state=self.state_file,
                viewport={"width": 1440, "height": 900},
                user_agent=self.user_agent
            )
            page = await context.new_page()
            try:
                await page.goto("https://www.naukri.com/mnjuser/profile", wait_until="domcontentloaded", timeout=25000)
                await page.wait_for_timeout(3500)

                profile_data = await page.evaluate("""() => {
                    const text = document.body.innerText;
                    const lines = text.split("\\n").map(l => l.trim()).filter(l => l.length > 0);
                    
                    let name = "";
                    let headline = "";
                    let company = "";
                    let location = "";
                    const tags = [];
                    
                    for (let i = 0; i < Math.min(lines.length, 30); i++) {
                        if (lines[i].startsWith("#")) {
                            tags.push(lines[i]);
                        }
                    }
                    
                    const searchIdx = lines.findIndex(l => l.includes("Search jobs"));
                    if (searchIdx !== -1 && lines.length > searchIdx + 4) {
                        name = lines[searchIdx + 1];
                        headline = lines[searchIdx + 2];
                        company = lines[searchIdx + 3].replace("@", "").trim();
                        location = lines[searchIdx + 4];
                    }
                    
                    const expIdx = lines.indexOf("Total experience");
                    const exp = expIdx !== -1 && lines.length > expIdx + 1 ? lines[expIdx + 1] : "";
                    
                    const noticeIdx = lines.indexOf("Notice period");
                    const notice = noticeIdx !== -1 && lines.length > noticeIdx + 1 ? lines[noticeIdx + 1] : "";

                    const salaryIdx = lines.indexOf("Current salary");
                    const salary = salaryIdx !== -1 && lines.length > salaryIdx + 1 ? lines[salaryIdx + 1] : "";
                    
                    return {
                        name,
                        headline,
                        company,
                        location,
                        tags,
                        total_experience: exp,
                        notice_period: notice,
                        current_salary: salary
                    };
                }""")

                profile_data["platform"] = "naukri"
                profile_data["status"] = "AUTHENTICATED"
                profile_data["profile_url"] = "https://www.naukri.com/mnjuser/profile"
                return profile_data
            except Exception as e:
                return {"platform": "naukri", "status": "ERROR", "error": str(e)}
            finally:
                await browser.close()

    async def search_jobs(self, keywords: str = "Automation QA", location: str = "India", limit: int = 10) -> List[Dict[str, Any]]:
        """Search Naukri job postings matching keywords headlessly in the background."""
        if not os.path.exists(self.state_file):
            return []

        kw_clean = keywords.lower().replace(" ", "-")
        url = f"https://www.naukri.com/{kw_clean}-jobs"

        results = []
        async with async_playwright() as p:
            browser = await _launch_headless_browser(p)
            context = await browser.new_context(
                storage_state=self.state_file,
                viewport={"width": 1440, "height": 900},
                user_agent=self.user_agent
            )
            page = await context.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                await page.wait_for_timeout(3000)
                cards = await page.locator(JOB_CARD_SELECTOR).all()
                for c in cards[:limit]:
                    details = await extract_card_details(c)
                    results.append({
                        "title": details["title"],
                        "company": details["company"],
                        "location": details["location"],
                        "experience": details["experience"],
                        "is_quick_apply": details["is_quick_apply"],
                        "is_external": details["is_external"]
                    })
            except Exception as e:
                print(f"Error searching Naukri jobs: {e}")
            finally:
                await browser.close()

        return results

    async def search_recruiters(self, company: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search active hiring postings and recruiter leads on Naukri for target company headlessly."""
        if not os.path.exists(self.state_file):
            return []

        company_clean = company.lower().replace(" ", "-")
        url = f"https://www.naukri.com/{company_clean}-jobs"
        results = []

        async with async_playwright() as p:
            browser = await _launch_headless_browser(p)
            context = await browser.new_context(
                storage_state=self.state_file,
                viewport={"width": 1440, "height": 900},
                user_agent=self.user_agent
            )
            page = await context.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                await page.wait_for_timeout(3000)
                cards = await page.locator(JOB_CARD_SELECTOR).all()
                for c in cards[:limit]:
                    details = await extract_card_details(c)
                    raw_text = details.get("raw_text", "")
                    emails = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", raw_text)
                    recruiter_name = None
                    for line in raw_text.splitlines():
                        if "posted by" in line.lower() or "recruiter" in line.lower():
                            recruiter_name = line.strip()
                            break

                    results.append({
                        "company": details["company"] or company,
                        "hiring_role": details["title"],
                        "location": details["location"],
                        "experience": details["experience"],
                        "quick_apply": details["is_quick_apply"],
                        "recruiter": recruiter_name or "Talent Acquisition Team",
                        "contact_email": emails[0] if emails else None
                    })
            except Exception as e:
                print(f"Error searching recruiters: {e}")
            finally:
                await browser.close()

        return results

    async def update_headline(self, new_headline: str) -> Dict[str, Any]:
        """Update candidate resume headline on Naukri profile headlessly."""
        if not os.path.exists(self.state_file):
            return {"status": "ERROR", "message": "Naukri not authenticated"}

        async with async_playwright() as p:
            browser = await _launch_headless_browser(p)
            context = await browser.new_context(
                storage_state=self.state_file,
                viewport={"width": 1440, "height": 900},
                user_agent=self.user_agent
            )
            page = await context.new_page()
            try:
                await page.goto("https://www.naukri.com/mnjuser/profile", wait_until="domcontentloaded", timeout=25000)
                await page.wait_for_timeout(3500)
                
                # Check for classic edit icon
                edit_icon = page.locator("span:has-text('Resume Headline') ~ span.edit, .resumeHeadline .edit").first
                if await edit_icon.count() > 0:
                    await edit_icon.click()
                    await page.wait_for_timeout(1000)
                    textarea = page.locator("#resumeHeadlineTxt, textarea[name='resumeHeadline']").first
                    await textarea.fill(new_headline)
                    save_btn = page.locator("button:has-text('Save'), .btn-save").first
                    await save_btn.click()
                    await page.wait_for_timeout(2000)
                    return {"status": "SUCCESS", "new_headline": new_headline}

                # TopTier view: headline is driven by active profile role & resume
                current_profile = await self.get_profile(live=False)
                return {
                    "status": "NOTICE",
                    "view_type": "Naukri TopTier",
                    "proposed_headline": new_headline,
                    "current_status": current_profile.get("status"),
                    "message": "Naukri TopTier active. Profile headline is synced automatically from your active primary role ('Staff SDET @ AlphaSense') and attached resume."
                }
            except Exception as e:
                return {"status": "ERROR", "error": str(e)}
            finally:
                await browser.close()
