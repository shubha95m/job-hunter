"""
Naukri DOM Selectors and Card Parser.
Provides robust element locators and card extraction for modern Naukri UI.
"""

from typing import Dict, Any, List, Optional
from playwright.async_api import Page, Locator


# Modern Naukri Selectors
JOB_CARD_SELECTOR = (
    "div[class*='rounded-3xl'][class*='cursor-pointer'], "
    "div.cursor-pointer[class*='min-h'], "
    ".jobTuple, "
    "div.srp-jobtuple-wrapper"
)

QUICK_APPLY_BUTTON_SELECTOR = (
    "span:text-is('Quick apply'), "
    "span:has-text('Quick apply'), "
    "button:has-text('Quick apply'), "
    "button:has-text('Apply')"
)

JOB_TITLE_SELECTOR = (
    "div[class*='text-title18Sb']",
    "a.title",
    "h2",
    "h3"
)

QUESTIONNAIRE_DRAWER_SELECTOR = (
    "div.chatbot_drawer, "
    "[role='dialog'], "
    "div[class*='drawer'], "
    "div[class*='modal']"
)


async def extract_card_details(card: Locator) -> Dict[str, Any]:
    """Extract structured job metadata from a Naukri search card."""
    raw_text = (await card.inner_text()).strip()
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]

    # Default fallbacks
    company = lines[0] if lines else "Unknown Company"
    title = "Unknown Position"
    location = "India"
    experience = ""
    skills = []

    # First attempt: locator by strict title class
    try:
        title_el = card.locator("div[class*='text-title18Sb'], a.title, h2, h3").first
        if await title_el.count() > 0:
            candidate_title = (await title_el.inner_text()).strip()
            if candidate_title and "\n" not in candidate_title:
                title = candidate_title
    except Exception:
        pass

    # Second attempt: scan text lines for the job title
    if title == "Unknown Position" or "\n" in title:
        role_keywords = ["engineer", "developer", "lead", "sdet", "qa", "architect", "manager", "tester", "quality assurance"]
        for line in lines:
            line_lower = line.lower()
            # Ignore company name, ratings, tags, timestamps
            if line == company or re.match(r"^\d+(\.\d+)?$", line) or line.endswith("ago") or "employees" in line_lower or "quick apply" in line_lower or "applied" in line_lower:
                continue
            if any(rw in line_lower for rw in role_keywords):
                title = line
                break


    # Extract location and experience
    for line in lines:
        if "yrs" in line.lower() or "years" in line.lower():
            experience = line
        elif any(city in line.lower() for city in ["bengaluru", "bangalore", "pune", "mumbai", "hyderabad", "delhi", "noida", "remote", "hybrid"]):
            location = line

    is_quick_apply = "quick apply" in raw_text.lower()
    is_external = "on company site" in raw_text.lower() or "company site" in raw_text.lower()
    is_applied = "applied" in raw_text.lower() and not is_quick_apply

    return {
        "title": title,
        "company": company,
        "location": location,
        "experience": experience,
        "is_quick_apply": is_quick_apply,
        "is_external": is_external,
        "is_applied": is_applied,
        "raw_text": raw_text
    }
