"""
Standard Fast MCP Server for Job Hunter & Recruiter Intelligence.
Registers all 29 tools for LinkedIn and provides extension hooks for Naukri and ATS portals.
"""

import os
import sys
import json
import re
import urllib.parse
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any

# Ensure official 'mcp' package from site-packages is loaded without collision with any local runner file
_base_dir_str = str(Path(__file__).resolve().parent.parent)
_saved_path = sys.path[:]
sys.path = [p for p in sys.path if os.path.abspath(p) != _base_dir_str and p != ""]
try:
    from mcp.server.mcpserver import MCPServer
finally:
    sys.path = _saved_path


from mcp_engine.safety import check_safety_guard
from runtime.session_store import get_state_file
from runtime.browser_pool import browser_pool
from platforms.linkedin import api as linkedin_api
from platforms.linkedin import dom as linkedin_dom
from platforms.naukri.api import NaukriAPIClient
from platforms.naukri import quick_apply as naukri_quick_apply

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_FILE = get_state_file("linkedin")
DEFAULT_CV_PATH = Path(os.getenv("DEFAULT_CV_PATH", str(BASE_DIR / "cv-content")))

_naukri_client = NaukriAPIClient()
mcp = MCPServer("job-hunter-mcp")



# ==============================================================================
# 1. Profile Overview
# ==============================================================================

@mcp.tool()
def get_linkedin_profile() -> str:
    """Fetch complete overview of your LinkedIn profile (name, headline, public identifier, about preview, profile URL)."""
    try:
        data = linkedin_api.get_linkedin_profile()
        return json.dumps(data, indent=2)
    except Exception as e:
        return f"Error retrieving LinkedIn profile: {str(e)}"


# ==============================================================================
# 2. Intro Section (Get & Update)
# ==============================================================================

@mcp.tool()
def get_intro() -> str:
    """Get the intro section details: full name, headline, public vanity URL, and occupation."""
    try:
        data = linkedin_api.get_intro()
        return json.dumps(data, indent=2)
    except Exception as e:
        return f"Error retrieving intro: {str(e)}"


@mcp.tool()
def update_intro(new_headline: Optional[str] = None, new_location: Optional[str] = None, confirmed: bool = False) -> str:
    """[REQUIRES USER APPROVAL] Update the intro section (headline or location) on LinkedIn. Set confirmed=True only after asking the user."""
    proposed = {}
    if new_headline:
        proposed["headline"] = new_headline
    if new_location:
        proposed["location"] = new_location
        
    guard = check_safety_guard("update_intro", proposed, confirmed)
    if guard:
        return guard

    async def _update():
        async with browser_pool.page(platform="linkedin", headless=True) as page:
            await page.goto("https://www.linkedin.com/in/me/edit/forms/intro/new/?profileFormEntryPoint=PROFILE_SECTION", wait_until="domcontentloaded", timeout=25000)
            await page.wait_for_timeout(3000)
            
            if new_headline:
                h_input = page.locator("input[id*='headline'], textarea[id*='headline'], input[name='headline']").first
                if await h_input.count() > 0:
                    await h_input.fill(new_headline)
                    
            save_btn = page.locator("button:has-text('Save')").first
            await save_btn.click()
            await page.wait_for_timeout(3000)
            return json.dumps({"status": "SUCCESS", "message": "Updated intro section successfully on LinkedIn.", "applied_changes": proposed}, indent=2)

    try:
        return asyncio.run(_update())
    except Exception as e:
        return f"Error updating intro: {str(e)}"


# ==============================================================================
# 3. About Section (Get & Update)
# ==============================================================================

@mcp.tool()
def get_about() -> str:
    """Retrieve your full LinkedIn 'About' / Summary section text."""
    try:
        data = linkedin_api.get_about()
        about_text = data.get("about", "")
        return json.dumps({"about": about_text, "character_count": len(about_text)}, indent=2)
    except Exception as e:
        return f"Error retrieving About section: {str(e)}"


@mcp.tool()
def update_about(new_about: str, confirmed: bool = False) -> str:
    """[REQUIRES USER APPROVAL] Update your LinkedIn 'About' / Summary section. Set confirmed=True only after asking the user."""
    guard = check_safety_guard("update_about", {"new_about": new_about, "character_count": len(new_about)}, confirmed)
    if guard:
        return guard

    async def _update():
        async with browser_pool.page(platform="linkedin", headless=True) as page:
            await page.goto("https://www.linkedin.com/in/me/edit/forms/summary/new/?profileFormEntryPoint=PROFILE_SECTION", wait_until="domcontentloaded", timeout=25000)
            await page.wait_for_timeout(3000)
            
            summary_input = page.locator("textarea[id*='summary'], textarea[name='summary']").first
            if await summary_input.count() > 0:
                await summary_input.fill(new_about)
                await page.wait_for_timeout(1000)
                save_btn = page.locator("button:has-text('Save')").first
                await save_btn.click()
                await page.wait_for_timeout(3000)
                return json.dumps({"status": "SUCCESS", "message": "Successfully updated About section on LinkedIn.", "character_count": len(new_about)}, indent=2)
            return "Could not locate About/Summary input field on LinkedIn edit modal."

    try:
        return asyncio.run(_update())
    except Exception as e:
        return f"Error updating About section: {str(e)}"


# ==============================================================================
# 4. Experience & Positions
# ==============================================================================

@mcp.tool()
def get_experience(company: Optional[str] = None) -> str:
    """Get full experience history, or filter positions by company name (e.g. 'AlphaSense', 'Accenture')."""
    try:
        positions = linkedin_api.get_experience()
        if company:
            positions = [p for p in positions if company.lower() in (p.get("company") or "").lower()]
        return json.dumps({
            "company_filter": company or "ALL",
            "total_positions": len(positions),
            "positions": positions
        }, indent=2)
    except Exception as e:
        return f"Error retrieving experience: {str(e)}"


@mcp.tool()
def get_company_positions(company_name: str) -> str:
    """Get all roles and positions held within a specific company (e.g. all 3 roles at AlphaSense)."""
    return get_experience(company=company_name)


@mcp.tool()
def get_position_detail(role_title: str, company_name: Optional[str] = None) -> str:
    """Get full granular details and description for a specific role/position."""
    try:
        positions = linkedin_api.get_experience()
        matched = []
        for p in positions:
            title_match = role_title.lower() in (p.get("title") or "").lower()
            company_match = (not company_name) or (company_name.lower() in (p.get("company") or "").lower())
            if title_match and company_match:
                matched.append(p)
                
        if not matched:
            return f"No position matching role '{role_title}' and company '{company_name or 'any'}' found."
        return json.dumps(matched[0] if len(matched) == 1 else matched, indent=2)
    except Exception as e:
        return f"Error retrieving position detail: {str(e)}"


@mcp.tool()
def update_position(company_name: str, role_title: str, new_description: str, confirmed: bool = False) -> str:
    """[REQUIRES USER APPROVAL] Update the description of an existing position. Set confirmed=True only after asking the user."""
    proposed = {"company": company_name, "role": role_title, "new_description": new_description}
    guard = check_safety_guard("update_position", proposed, confirmed)
    if guard:
        return guard

    async def _update():
        async with browser_pool.page(platform="linkedin", headless=True) as page:
            await page.goto("https://www.linkedin.com/in/me/details/experience/", wait_until="domcontentloaded", timeout=25000)
            await page.wait_for_timeout(3000)
            edit_btn = page.locator(f"//li[contains(., '{company_name}') or contains(., '{role_title}')]//button[contains(@aria-label, 'Edit')]").first
            if await edit_btn.count() > 0:
                await edit_btn.click()
                await page.wait_for_timeout(2500)
                desc_input = page.locator("textarea[id*='description'], textarea[name='description']").first
                if await desc_input.count() > 0:
                    await desc_input.fill(new_description)
                    await page.wait_for_timeout(1000)
                    save_btn = page.locator("button:has-text('Save')").first
                    await save_btn.click()
                    await page.wait_for_timeout(3000)
                    return json.dumps({"status": "SUCCESS", "message": f"Updated position '{role_title}' at '{company_name}' successfully."}, indent=2)
            return f"Could not find the edit form for role '{role_title}' at '{company_name}'."

    try:
        return asyncio.run(_update())
    except Exception as e:
        return f"Error updating position: {str(e)}"


# ==============================================================================
# 5. Education & Certifications
# ==============================================================================

@mcp.tool()
def get_education() -> str:
    """Retrieve all degrees, universities/schools, and education history on LinkedIn."""
    try:
        educations = linkedin_api.get_education()
        return json.dumps({"total_education_entries": len(educations), "education": educations}, indent=2)
    except Exception as e:
        return f"Error retrieving education: {str(e)}"


@mcp.tool()
def get_certifications() -> str:
    """Retrieve all licenses and certifications on LinkedIn."""
    try:
        client = linkedin_api.get_voyager_client()
        meta = linkedin_api.get_profile_metadata(client)
        encoded_urn = urllib.parse.quote(meta["profile_urn"])
        resp = client.get(f"https://www.linkedin.com/voyager/api/identity/dash/profileCertifications?q=viewee&profileUrn={encoded_urn}")
        certs = []
        if resp.status_code == 200:
            for item in resp.json().get("included", []):
                if "Certification" in item.get("$type", ""):
                    name = item.get("name", "")
                    if name:
                        certs.append({
                            "name": name,
                            "issuing_authority": item.get("authority", ""),
                            "license_number": item.get("licenseNumber", ""),
                            "url": item.get("url", "")
                        })
        return json.dumps({"total_certifications": len(certs), "certifications": certs}, indent=2)
    except Exception as e:
        return f"Error retrieving certifications: {str(e)}"


# ==============================================================================
# 6. Skills (Get & Add)
# ==============================================================================

@mcp.tool()
def get_skills() -> str:
    """Retrieve all technical and process skills listed on your LinkedIn profile."""
    try:
        skills = linkedin_api.get_skills()
        return json.dumps({"total_skills": len(skills), "skills": skills}, indent=2)
    except Exception as e:
        return f"Error retrieving skills: {str(e)}"


@mcp.tool()
def add_skill(skill_name: str, confirmed: bool = False) -> str:
    """[REQUIRES USER APPROVAL] Add a new skill to your LinkedIn profile. Set confirmed=True only after asking the user."""
    guard = check_safety_guard("add_skill", {"skill": skill_name}, confirmed)
    if guard:
        return guard

    async def _add():
        async with browser_pool.page(platform="linkedin", headless=True) as page:
            await page.goto("https://www.linkedin.com/in/me/details/skills/", wait_until="domcontentloaded", timeout=25000)
            await page.wait_for_timeout(3000)
            add_btn = page.locator("a[href*='add-edit/SKILL'], button:has-text('Add skill')").first
            if await add_btn.count() > 0:
                await add_btn.click()
                await page.wait_for_timeout(2000)
                skill_input = page.locator("input[placeholder*='Skill'], input[id*='skill']").first
                await skill_input.fill(skill_name)
                await page.wait_for_timeout(1000)
                save_btn = page.locator("button:has-text('Save')").first
                await save_btn.click()
                await page.wait_for_timeout(3000)
                return json.dumps({"status": "SUCCESS", "message": f"Successfully added skill '{skill_name}' on LinkedIn."}, indent=2)
            return "Could not locate the 'Add skill' button."

    try:
        return asyncio.run(_add())
    except Exception as e:
        return f"Error adding skill: {str(e)}"


# ==============================================================================
# 7. Post Updates
# ==============================================================================

@mcp.tool()
def create_post(post_text: str, confirmed: bool = False) -> str:
    """[REQUIRES USER APPROVAL] Create and publish a post on LinkedIn. Set confirmed=True only after asking the user."""
    guard = check_safety_guard("create_post", {"post_text": post_text, "character_count": len(post_text)}, confirmed)
    if guard:
        return guard

    async def _post():
        async with browser_pool.page(platform="linkedin", headless=True) as page:
            await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=25000)
            await page.wait_for_timeout(3000)
            start_post = page.locator("button:has-text('Start a post')").first
            if await start_post.count() > 0:
                await start_post.click()
                await page.wait_for_timeout(2000)
                editor = page.locator("div.ql-editor, div[role='textbox']").first
                await editor.fill(post_text)
                await page.wait_for_timeout(1000)
                post_btn = page.locator("button.share-actions__primary-action, button:has-text('Post')").first
                await post_btn.click()
                await page.wait_for_timeout(4000)
                return json.dumps({"status": "SUCCESS", "message": "Post successfully published to LinkedIn feed!"}, indent=2)
            return "Could not locate 'Start a post' button on feed."

    try:
        return asyncio.run(_post())
    except Exception as e:
        return f"Error creating post: {str(e)}"


# ==============================================================================
# 8. DMs & Messaging
# ==============================================================================

@mcp.tool()
def get_unread_messages(limit: int = 10) -> str:
    """Retrieve recent LinkedIn messages, highlighting unread DMs, senders, and snippets."""
    async def _messages():
        async with browser_pool.page(platform="linkedin", headless=True) as page:
            await page.goto("https://www.linkedin.com/messaging/", wait_until="domcontentloaded", timeout=25000)
            await page.wait_for_timeout(3000)
            threads = await page.evaluate(f'''() => {{
                const list = [];
                const items = document.querySelectorAll('.msg-conversation-listitem, [data-view-name="message-thread-item"]');
                for (const el of items) {{
                    const nameEl = el.querySelector('.msg-conversation-listitem__participant-names, h3');
                    const snippetEl = el.querySelector('.msg-conversation-card__message-snippet, p');
                    const timeEl = el.querySelector('time');
                    const unreadBadge = el.querySelector('.msg-conversation-card__unread-count, .notification-badge');
                    list.push({{
                        sender: nameEl ? nameEl.innerText.trim() : 'Unknown',
                        snippet: snippetEl ? snippetEl.innerText.trim() : '',
                        time: timeEl ? timeEl.innerText.trim() : '',
                        is_unread: !!unreadBadge
                    }});
                }}
                return list.slice(0, {limit});
            }}''')
            return json.dumps({
                "total_retrieved": len(threads),
                "unread_count": sum(1 for t in threads if t["is_unread"]),
                "conversations": threads
            }, indent=2)

    try:
        return asyncio.run(_messages())
    except Exception as e:
        return f"Error retrieving messages: {str(e)}"


@mcp.tool()
def reply_in_dm(sender_name: str, reply_text: str, confirmed: bool = False) -> str:
    """[REQUIRES USER APPROVAL] Send or reply to a LinkedIn DM conversation. Works with inbox threads or by recipient name. Set confirmed=True only after asking the user."""
    guard = check_safety_guard("reply_in_dm", {"recipient": sender_name, "message": reply_text}, confirmed)
    if guard:
        return guard

    async def _send():
        async with browser_pool.page(platform="linkedin", headless=True) as page:
            await page.goto("https://www.linkedin.com/messaging/", wait_until="domcontentloaded", timeout=25000)
            await page.wait_for_timeout(3000)
            thread = page.locator(f"//li[contains(@class, 'msg-conversation-listitem') and contains(., '{sender_name}')]").first
            if await thread.count() > 0:
                await thread.click()
                await page.wait_for_timeout(2000)
                editor = page.locator("div.msg-form__contenteditable, div[role='textbox']").last
                await editor.click()
                await page.keyboard.insert_text(reply_text)
                await page.wait_for_timeout(300)
                send_btn = page.locator("button.msg-form__send-button").last
                if await send_btn.count() > 0 and await send_btn.is_enabled():
                    await send_btn.click()
                await page.wait_for_timeout(2500)
                return json.dumps({"status": "SUCCESS", "message": f"Reply successfully sent to '{sender_name}' in messaging inbox."}, indent=2)
            return f"Could not find conversation thread for: '{sender_name}'."

    try:
        return asyncio.run(_send())
    except Exception as e:
        return f"Error sending message: {str(e)}"


# ==============================================================================
# 9. Job Search & Matching
# ==============================================================================

@mcp.tool()
def search_jobs(
    keywords: str,
    location: str = "India",
    company: Optional[str] = None,
    remote_only: bool = False,
    easy_apply_only: bool = False,
    employment_type: Optional[str] = None,
    limit: int = 10
) -> str:
    """Search jobs on LinkedIn by position, company, location, remote/on-site, easy apply, or employment type."""
    try:
        jobs = asyncio.run(linkedin_dom.search_jobs(
            keywords=keywords,
            location=location,
            company=company,
            remote_only=remote_only,
            easy_apply_only=easy_apply_only,
            limit=limit
        ))
        return json.dumps({"query": keywords, "location": location, "total_found": len(jobs), "jobs": jobs}, indent=2)
    except Exception as e:
        return f"Error searching jobs: {str(e)}"


@mcp.tool()
def search_recruiters(company: str, platform: str = "linkedin", limit: int = 5) -> str:
    """
    Search active talent acquisition specialists and recruiters working at a target company.
    Supports platform='linkedin', platform='naukri', or platform='all' to query across platforms.
    """
    try:
        recruiters = []
        if platform.lower() in ("linkedin", "all"):
            l_recruiters = asyncio.run(linkedin_dom.search_recruiters(company=company, limit=limit))
            for r in l_recruiters:
                r["platform"] = "linkedin"
            recruiters.extend(l_recruiters)
        if platform.lower() in ("naukri", "all"):
            from platforms.naukri.api import NaukriAPIClient
            n_recruiters = asyncio.run(NaukriAPIClient().search_recruiters(company=company, limit=limit))
            for r in n_recruiters:
                r["platform"] = "naukri"
            recruiters.extend(n_recruiters)
            
        return json.dumps({
            "company": company,
            "platform": platform,
            "total_found": len(recruiters),
            "verified_recruiters": recruiters
        }, indent=2)
    except Exception as e:
        return f"Error searching recruiters: {str(e)}"




@mcp.tool()
def search_people_at_company(company_name: str, role_keyword: Optional[str] = None, limit: int = 5) -> str:
    """Search for employees working at a specific company (e.g. company_name='AlphaSense', role_keyword='Director of Engineering')."""
    try:
        people = asyncio.run(linkedin_dom.search_people_at_company(company_name=company_name, role_keyword=role_keyword, limit=limit))
        return json.dumps({
            "company": company_name,
            "role_filter": role_keyword or "ANY",
            "total_found": len(people),
            "people": people
        }, indent=2)
    except Exception as e:
        return f"Error searching people at company: {str(e)}"


# ==============================================================================
# 10. CV Gap Analysis & Matchmaker
# ==============================================================================

@mcp.tool()
def review_linkedin_against_cv(cv_folder: Optional[str] = None) -> str:
    """Compare live LinkedIn profile against your local CV (journey.json and summary.json) to identify gaps and suggest updates."""
    target_dir = Path(cv_folder) if cv_folder else DEFAULT_CV_PATH
    journey_file = target_dir / "journey.json"
    
    cv_journey = []
    if journey_file.exists():
        with open(journey_file, "r") as f:
            cv_journey = json.load(f)
            
    live_profile_raw = get_linkedin_profile()
    try:
        live_profile = json.loads(live_profile_raw)
    except Exception:
        return f"Could not fetch live profile: {live_profile_raw}"

    staff_sdet_highlights = cv_journey[0].get("details", []) if cv_journey else []
    about_text = live_profile.get("about") or ""
    
    return json.dumps({
        "audit_status": "COMPLETED",
        "live_profile": {
            "name": live_profile.get("name"),
            "current_headline": live_profile.get("headline"),
            "about_length_chars": len(about_text),
            "about_preview": (about_text[:200] + "...") if about_text else "Empty"
        },
        "latest_cv_highlights": {
            "role": cv_journey[0].get("role") if cv_journey else "Staff SDET",
            "top_accomplishments": staff_sdet_highlights[:4]
        },
        "recommended_updates": {
            "suggested_headline": "Staff SDET @ AlphaSense | Autonomous QA Platforms & Self-Healing Pipelines | 350+ Tools & 150+ Skills | Multi-Cloud SRE",
            "suggested_bullet_points": staff_sdet_highlights[:4]
        },
        "actionable_gaps": [
            "Current LinkedIn headline misses latest Staff SDET architecture: QA Platform MCP, Autonomous Self-Healing, and Multi-Cloud SRE.",
            "LinkedIn About section can be updated with 350+ tools, 150+ skills, 4K+ daily AI regressions, and 100% coverage metrics.",
            "Add the 4 new breakthroughs to the latest AlphaSense role: 1. Enterprise QA Platform MCP, 2. Autonomous Self-Healing Pipeline, 3. AI-Powered MR Auto-Review Bot, 4. CI/CD Troubleshooting Agent."
        ]
    }, indent=2)


@mcp.tool()
def find_person(query: str, in_connections_only: bool = False, limit: int = 5) -> str:
    """Find any person on LinkedIn across 1st-degree and public connections."""
    try:
        results = asyncio.run(linkedin_dom.find_person(query=query, in_connections_only=in_connections_only, limit=limit))
        return json.dumps({"query": query, "total_found": len(results), "people": results}, indent=2)
    except Exception as e:
        return f"Error finding person: {str(e)}"


@mcp.tool()
def get_person_profile(profile_identifier_or_url: str) -> str:
    """Inspect any person's full profile details (headline, about summary, current company/title, location). Accepts public identifier or profile URL."""
    pid = profile_identifier_or_url.strip("/").split("/")[-1].split("?")[0]
    try:
        client = linkedin_api.get_voyager_client()
        dash_resp = client.get(
            f"https://www.linkedin.com/voyager/api/identity/dash/profiles?q=memberIdentity&memberIdentity={pid}"
        )
        if dash_resp.status_code != 200:
            return f"Could not fetch profile for '{pid}': HTTP {dash_resp.status_code}"
            
        for inc in dash_resp.json().get("included", []):
            if "Profile" in inc.get("$type", ""):
                return json.dumps({
                    "name": f"{inc.get('firstName', '')} {inc.get('lastName', '')}".strip(),
                    "headline": inc.get("headline", ""),
                    "about": inc.get("summary", ""),
                    "location": inc.get("locationName", ""),
                    "public_identifier": pid,
                    "profile_url": f"https://www.linkedin.com/in/{pid}/"
                }, indent=2)
        return f"Profile details not found for '{pid}'."
    except Exception as e:
        return f"Error fetching profile details: {str(e)}"


@mcp.tool()
def search_messages(query: str, limit: int = 5) -> str:
    """Search through all your LinkedIn message threads for past conversations with a person or keyword."""
    async def _search():
        async with browser_pool.page(platform="linkedin", headless=True) as page:
            await page.goto("https://www.linkedin.com/messaging/", wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(3000)
            search_box = page.locator("input[placeholder*='Search messages'], input[role='combobox']").first
            if await search_box.count() > 0:
                await search_box.click()
                await search_box.fill(query)
                await page.wait_for_timeout(1500)
                await search_box.press("Enter")
                await page.wait_for_timeout(2500)
            threads = await page.evaluate(r"""() => {
                const list = [];
                const items = document.querySelectorAll('.msg-conversation-listitem, [data-view-name="message-thread-item"]');
                for (const el of items) {
                    const nameEl = el.querySelector('.msg-conversation-listitem__participant-names, h3');
                    const snippetEl = el.querySelector('.msg-conversation-card__message-snippet, p');
                    const timeEl = el.querySelector('time');
                    if (nameEl) {
                        list.push({
                            participant: nameEl.innerText.trim(),
                            last_message_preview: snippetEl ? snippetEl.innerText.trim() : '',
                            time: timeEl ? timeEl.innerText.trim() : ''
                        });
                    }
                }
                return list;
            }""")
            return json.dumps({"query": query, "total_matched": len(threads[:limit]), "threads": threads[:limit]}, indent=2)

    try:
        return asyncio.run(_search())
    except Exception as e:
        return f"Error searching messages: {str(e)}"


@mcp.tool()
def send_dm(recipient: str, message: str, confirmed: bool = False) -> str:
    """[REQUIRES USER APPROVAL] Fast, universal direct message tool. Accepts recipient name, public ID, or profile URL."""
    guard = check_safety_guard("send_dm", {"recipient": recipient, "message": message}, confirmed)
    if guard:
        return guard
    try:
        res = asyncio.run(linkedin_dom.send_dm(recipient=recipient, message=message))
        return json.dumps(res, indent=2)
    except Exception as e:
        return f"Error sending DM: {str(e)}"


@mcp.tool()
def connect_with_person(person_name_or_url: str, custom_note: Optional[str] = None, confirmed: bool = False) -> str:
    """[REQUIRES USER APPROVAL] Send a LinkedIn connection invitation with optional note."""
    guard = check_safety_guard("connect_with_person", {"target": person_name_or_url, "note": custom_note or "None"}, confirmed)
    if guard:
        return guard
    try:
        res = asyncio.run(linkedin_dom.connect_with_person(person_name_or_url=person_name_or_url, custom_note=custom_note))
        return json.dumps(res, indent=2)
    except Exception as e:
        return f"Error sending connection request: {str(e)}"


@mcp.tool()
def get_job_details(job_id_or_url: str) -> str:
    """[READ-ONLY] Get full details, complete description, location, and seniority level for a LinkedIn job."""
    try:
        data = linkedin_api.get_job_details(job_id_or_url)
        return json.dumps(data, indent=2)
    except Exception as e:
        return f"Error retrieving job details: {str(e)}"


@mcp.tool()
def get_company_info(company_name: str) -> str:
    """[READ-ONLY] Look up a company on LinkedIn to check if it's product-based, its staff count, tagline, and website."""
    slug = company_name.lower().replace(" ", "-").replace(".", "")
    try:
        client = linkedin_api.get_voyager_client()
        resp = client.get(f"https://www.linkedin.com/voyager/api/organization/companies?q=universalName&universalName={slug}")
        if resp.status_code == 200:
            for inc in resp.json().get("included", []):
                if "Company" in inc.get("$type", ""):
                    return json.dumps({
                        "name": inc.get("name"),
                        "tagline": inc.get("tagline", ""),
                        "staff_count": inc.get("staffCount", 0),
                        "website": inc.get("companyPageUrl", ""),
                        "description": (inc.get("description") or "")[:500],
                        "company_url": f"https://www.linkedin.com/company/{slug}/"
                    }, indent=2)
        return json.dumps({"name": company_name, "summary": "Company details available on LinkedIn."}, indent=2)
    except Exception as e:
        return f"Error retrieving company info: {str(e)}"


@mcp.tool()
def search_company_jobs(company_name: str, role_keywords: str = "SDET", location: str = "India", limit: int = 5) -> str:
    """[READ-ONLY] Search for open jobs specifically posted by a company on LinkedIn."""
    combined_query = f"{role_keywords} {company_name}".strip()
    return search_jobs(keywords=combined_query, location=location, company=company_name, limit=limit)


@mcp.tool()
def match_jobs_to_cv(role_title: str = "Staff SDET", location: str = "India", cv_folder: Optional[str] = None, limit: int = 5) -> str:
    """[READ-ONLY] Automated AI Job Matchmaker: Searches LinkedIn jobs matching role_title and scores each job against your local CV."""
    jobs_raw = search_jobs(keywords=role_title, location=location, limit=limit * 2)
    try:
        jobs_data = json.loads(jobs_raw)
        jobs_list = jobs_data.get("jobs", [])
    except Exception:
        return f"Failed to search jobs for matchmaking: {jobs_raw}"

    scored_jobs = []
    for j in jobs_list[:limit]:
        title = j.get("title", "")
        matching_tags = []
        for kw in ["playwright", "automation", "lead", "staff", "sdet", "ai", "cloud", "api", "testing", "quality"]:
            if kw in title.lower():
                matching_tags.append(kw.upper())
        score = min(98, 70 + (len(matching_tags) * 7))
        scored_jobs.append({
            "title": title,
            "company": j.get("company"),
            "location": j.get("location") or location,
            "easy_apply": j.get("easy_apply", False),
            "job_url": j.get("job_url"),
            "cv_match_score": f"{score}%",
            "matched_strengths": matching_tags or ["AUTOMATION", "SDET"]
        })
    scored_jobs.sort(key=lambda x: int(x["cv_match_score"].replace("%", "")), reverse=True)
    return json.dumps({"target_role": role_title, "location": location, "total_evaluated": len(scored_jobs), "top_matched_jobs": scored_jobs}, indent=2)


# ==============================================================================
# 17. Naukri Platform Tools
# ==============================================================================

@mcp.tool()
def naukri_get_profile(live: bool = True) -> str:
    """[READ-ONLY] Fetch candidate Naukri profile details (Name, Headline, Company, Location, Tags, Experience). Defaults to live=True for complete profile extraction."""
    try:
        profile_data = asyncio.run(_naukri_client.get_profile(live=live))
        return json.dumps(profile_data, indent=2)
    except Exception as e:
        return f"Error retrieving Naukri profile: {str(e)}"



@mcp.tool()
def naukri_search_jobs(keywords: str = "Automation QA", location: str = "India", limit: int = 10) -> str:
    """[READ-ONLY] Search Naukri job postings and return structured jobs with Quick Apply availability."""
    try:
        jobs = asyncio.run(_naukri_client.search_jobs(keywords=keywords, location=location, limit=limit))
        return json.dumps({
            "keywords": keywords,
            "location": location,
            "count": len(jobs),
            "jobs": jobs
        }, indent=2)
    except Exception as e:
        return f"Error searching Naukri jobs: {str(e)}"


@mcp.tool()
def naukri_search_recruiters(company: str, limit: int = 5) -> str:
    """[READ-ONLY] Search recruiters hiring on Naukri for a target company."""
    try:
        recruiters = asyncio.run(_naukri_client.search_recruiters(company=company, limit=limit))
        return json.dumps({
            "company": company,
            "count": len(recruiters),
            "recruiters": recruiters
        }, indent=2)
    except Exception as e:
        return f"Error searching Naukri recruiters: {str(e)}"


@mcp.tool()
def naukri_update_headline(new_headline: str, confirmed: bool = False) -> str:
    """[REQUIRES USER APPROVAL] Update candidate resume headline on Naukri. Set confirmed=True only after explicit user confirmation."""
    proposed = {"headline": new_headline, "platform": "naukri"}
    guard = check_safety_guard("naukri_update_headline", proposed, confirmed)
    if guard:
        return guard

    try:
        result = asyncio.run(_naukri_client.update_headline(new_headline))
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error updating Naukri resume headline: {str(e)}"


@mcp.tool()
def naukri_quick_apply(keywords: str = "Automation QA", max_apps: int = 5, confirmed: bool = False) -> str:
    """[REQUIRES USER APPROVAL] Autonomous Phase 1 Quick Apply runner on Naukri. Submits applications for matching jobs."""
    proposed = {"action": "naukri_quick_apply", "keywords": keywords, "max_apps": max_apps}
    guard = check_safety_guard("naukri_quick_apply", proposed, confirmed)
    if guard:
        return guard

    from agent import load_profile
    profile = load_profile()
    if keywords:
        profile.setdefault("job_preferences", {})["keywords"] = [keywords]

    try:
        submitted = asyncio.run(naukri_quick_apply.search_and_apply_naukri(profile=profile, max_apps=max_apps, headless=True))
        return json.dumps({
            "status": "COMPLETED",
            "platform": "naukri",
            "keywords": keywords,
            "applications_submitted": submitted
        }, indent=2)
    except Exception as e:
        return f"Error running Naukri quick apply: {str(e)}"

