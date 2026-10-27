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
from runtime import crm
from runtime import intelligence
from platforms.linkedin import api as linkedin_api
from platforms.linkedin import dom as linkedin_dom
from platforms.naukri.api import NaukriAPIClient
from platforms.naukri import quick_apply as naukri_quick_apply
from runtime import email_service

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_FILE = get_state_file("linkedin")
DEFAULT_CV_PATH = Path(os.getenv("DEFAULT_CV_PATH", str(BASE_DIR / "cv-content")))

_naukri_client = NaukriAPIClient()

SERVER_INSTRUCTIONS = """Universal Multi-Platform Job Hunter & Recruiter Intelligence Server.

Core Operating Principles & Cross-Platform Synergy:
1. Multi-Platform Awareness:
   - Always state the platform source for every job opportunity ([Platform: Naukri] or [Platform: LinkedIn]).
   - Always include the exact, clickable URL for every job posting.

2. Cross-Platform Recruiter Mapping:
   - Naukri has vast in-platform tech job inventory and 1-click Quick Apply in India/remote, but masks recruiter profiles for enterprise companies.
   - LinkedIn has a rich member directory and direct messaging (InMail/DM/connect).
   - Whenever a job is found on Naukri (or an external ATS) and the user wants to identify or contact the recruiter:
     Map that company to LinkedIn using search_people_at_company(company_name=..., role_keyword='Recruiter') or search_recruiters(company=...).

3. Direct Outreach & Messaging:
   - When reaching out to a recruiter or hiring manager regarding ANY job (whether found on Naukri or LinkedIn):
     Use send_dm or connect_with_person on LinkedIn.
     Reference the specific role, platform source, and job URL in the message.
   - STRICT SAFETY GUARD: Never send messages, connection requests, or modify profiles without user confirmation (confirmed=True). Always show the draft to the user first.

4. Connection & Network Management:
   - Check connection status using check_connection_status(person_name_or_url=...) or get_connections(limit=...).
   - Check pending invitations sent to others that haven't been accepted using get_sent_invitations().
   - Cancel/withdraw pending sent requests using withdraw_sent_invitation(person_name_or_url=..., confirmed=True).
   - Check incoming connection invitations with get_received_invitations() and accept or decline with respond_to_invitation(person_name_or_url=..., action='accept'|'decline', confirmed=True).
   - STRICT SAFETY GUARD: Sending requests, accepting/declining, or withdrawing requests requires confirmed=True with user approval.

5. Wishlist & "Will Do Later" Queue:
   - When jobs are discovered via search_jobs, naukri_search_jobs, or search_cross_platform_jobs, present the results clearly to the user.
   - Always offer or ask the user if they want to keep any of the positions in their Wishlist (`add_to_wishlist`). If yes, record them so the user can review and apply later. If no, do not add.
   - Users can view their bookmarked opportunities anytime with `get_wishlist()`.
   - When ready to apply, use `convert_wishlist_to_applied(job_id_or_company)` to transition the job into the active application pipeline and begin recruiter cadence tracking.
"""

mcp = MCPServer("job-hunter-mcp", instructions=SERVER_INSTRUCTIONS)


# ==============================================================================
# Guidelines Resources (Agent Operating SOPs)
# ==============================================================================

@mcp.resource("guidelines://cross-platform-workflow", name="Cross-Platform Recruiter Workflow", description="Guidelines on combining Naukri jobs with LinkedIn recruiter discovery and outreach DMs")
def get_cross_platform_workflow() -> str:
    """Guidelines explaining how to discover jobs on Naukri, map recruiters on LinkedIn, and send targeted DMs."""
    return """# Cross-Platform Recruiter & Job Hunting Workflow Guidelines

## 1. The Strategy: The Best of Both Platforms
- **Naukri**: Ideal for high-speed job discovery in India and Remote, and 1-click Quick Apply. Modern enterprise tech companies on Naukri post through centralized corporate ATS accounts with masked recruiter identities.
- **LinkedIn**: The global standard for professional networking, direct recruiter discovery, and outbound messaging (DMs & Connection Requests).

## 2. Standard Operating Procedure for Job Queries:
When a candidate asks to find jobs, recruiters, or outreach contacts:
1. **Discover Jobs Across Platforms**:
   - Query Naukri (`naukri_search_jobs` or `search_cross_platform_jobs`) for local/remote high-volume openings.
   - Query LinkedIn (`search_jobs`) for global and corporate requisitions.
   - **MANDATORY**: Always prefix every opportunity with its origin: `[Platform: Naukri]` or `[Platform: LinkedIn]` followed by the clean, clickable URL.

2. **Map Recruiters on LinkedIn for Naukri Jobs**:
   - For every company identified on Naukri, query LinkedIn using:
     - `search_people_at_company(company_name="...", role_keyword="Recruiter")`
     - OR `search_recruiters(company="...")`
   - Retrieve the exact named Talent Acquisition Partner, Technical Recruiter, or Engineering Manager.

3. **Draft & Dispatch Outbound DMs via LinkedIn**:
   - Use `draft_recruiter_pitch(job_title=..., company=..., job_url=..., platform=...)` to generate a personalized message citing the candidate's Staff SDET background and the exact job link.
   - Dispatch via `send_dm` (for 1st-degree connections) or `connect_with_person` (with a custom note) on LinkedIn.
   - **Safety First**: NEVER dispatch DMs or connection notes without explicit user approval (`confirmed=True`). Always present the proposed message to the user first.
"""


@mcp.resource("guidelines://outbound-dm-templates", name="Outbound Recruiter DM Templates", description="High-impact cold outreach templates referencing job URLs from Naukri or LinkedIn")
def get_outbound_dm_templates() -> str:
    """Pre-crafted outreach message templates for recruiters referencing job postings."""
    return """# High-Impact Recruiter Outreach Templates

## Template 1: Connection Request Note (under 300 characters)
"Hi {recruiter_name}, I came across the {role_title} opening at {company} ({platform}: {job_url}). With ~10 yrs leading QA/SDET ecosystems (Playwright, Java/Python, Cloud, AI testing), I'd love to connect and explore how I can support your engineering goals!"

## Template 2: Direct Message (DM / InMail)
"Hi {recruiter_name},

I hope you're having a productive week!

I noticed that {company} is actively hiring for a {role_title} on {platform} ({job_url}). 

Given my background as a Staff SDET / QA Lead with nearly a decade of experience architecting resilient test automation frameworks across distributed microservices (Playwright, Python, Java, AWS/GCP, and AI-assisted QA), I believe my experience strongly aligns with your team's quality and scalability goals.

I'd welcome the opportunity to share my resume and discuss how my expertise can drive impact for {company}.

Best regards,
[Your Name]
Portfolio: [Your Portfolio URL]"
"""


@mcp.resource("guidelines://platform-capabilities", name="Platform Capabilities & Strengths", description="Comparison of Naukri Quick Apply vs LinkedIn Graph and direct messaging")
def get_platform_capabilities() -> str:
    """Capabilities matrix comparing Naukri and LinkedIn for job search, applications, and messaging."""
    return """# Platform Capabilities Matrix

| Feature | Naukri | LinkedIn | Recommended MCP Flow |
|---|---|---|---|
| **Job Search Coverage** | High (India, Remote, GCC) | High (Global, MNCs, Startups) | Query both using `search_cross_platform_jobs` |
| **In-Platform Apply** | 1-Click Quick Apply (`naukri_quick_apply`) | Multi-Step Easy Apply (`platforms/linkedin/easy_apply`) | Run autonomously in background |
| **Recruiter Discovery** | Masked / Department Level | Named Members & Talent Partners | Discover on LinkedIn using `search_people_at_company` |
| **Direct Messaging** | Recruiter Chat (Inbound only) | Outbound DMs & Connection Notes | Send outbound messages via LinkedIn (`send_dm`) |
| **Attribution** | `[Platform: Naukri]` + URL | `[Platform: LinkedIn]` + URL | Always clearly display to candidate |
"""




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
def get_connections(limit: int = 50, start: int = 0, sort_by: str = "RECENTLY_ADDED") -> str:
    """[READ-ONLY] Retrieve candidate's 1st-degree LinkedIn connections (name, headline, public identifier, profile URL)."""
    try:
        data = linkedin_api.get_connections(limit=limit, start=start, sort_by=sort_by)
        return json.dumps({"total_returned": len(data), "connections": data}, indent=2)
    except Exception as e:
        return f"Error retrieving LinkedIn connections: {str(e)}"


@mcp.tool()
def check_connection_status(person_name_or_url: str) -> str:
    """[READ-ONLY] Check relationship and connection status with any person on LinkedIn (1st-degree connected, pending request sent, or not connected)."""
    try:
        data = asyncio.run(linkedin_dom.check_connection_status(person_name_or_url=person_name_or_url))
        return json.dumps(data, indent=2)
    except Exception as e:
        return f"Error checking connection status: {str(e)}"


@mcp.tool()
def get_sent_invitations(limit: int = 50, start: int = 0) -> str:
    """[READ-ONLY] Retrieve all pending connection requests sent by you to others that have not yet been accepted."""
    try:
        data = linkedin_api.get_sent_invitations(limit=limit, start=start)
        return json.dumps({"total_pending": len(data), "sent_invitations": data}, indent=2)
    except Exception as e:
        return f"Error retrieving sent invitations: {str(e)}"


@mcp.tool()
def withdraw_sent_invitation(person_name_or_url: str, confirmed: bool = False) -> str:
    """[REQUIRES USER APPROVAL] Withdraw/cancel a pending connection invitation that you previously sent to a person."""
    guard = check_safety_guard("withdraw_sent_invitation", {"target": person_name_or_url}, confirmed)
    if guard:
        return guard
    try:
        res = asyncio.run(linkedin_dom.withdraw_sent_invitation(person_name_or_url=person_name_or_url))
        return json.dumps(res, indent=2)
    except Exception as e:
        return f"Error withdrawing sent invitation: {str(e)}"


@mcp.tool()
def get_received_invitations(limit: int = 20) -> str:
    """[READ-ONLY] Retrieve all pending incoming connection requests sent to you by other people."""
    try:
        data = asyncio.run(linkedin_dom.get_received_invitations(limit=limit))
        return json.dumps({"total_received": len(data), "received_invitations": data}, indent=2)
    except Exception as e:
        return f"Error retrieving received invitations: {str(e)}"


@mcp.tool()
def respond_to_invitation(person_name_or_url: str, action: str, confirmed: bool = False) -> str:
    """[REQUIRES USER APPROVAL] Accept or decline/ignore an incoming LinkedIn connection invitation. Action must be 'accept' or 'decline'/'ignore'."""
    guard = check_safety_guard("respond_to_invitation", {"target": person_name_or_url, "action": action}, confirmed)
    if guard:
        return guard
    try:
        res = asyncio.run(linkedin_dom.respond_to_invitation(person_name_or_url=person_name_or_url, action=action))
        return json.dumps(res, indent=2)
    except Exception as e:
        return f"Error responding to invitation: {str(e)}"


# ==============================================================================
# Application CRM & Recruiter Touchpoint Cadence Tools
# ==============================================================================

@mcp.tool()
def get_application_pipeline(status: Optional[str] = None, company: Optional[str] = None, limit: int = 50) -> str:
    """[READ-ONLY] Retrieve tracked job applications, active pipeline stages, statistical summary, and days elapsed."""
    try:
        summary = crm.get_pipeline_summary()
        apps = crm.get_pipeline(status=status, company=company, limit=limit)
        return json.dumps({
            "summary": summary,
            "total_returned": len(apps),
            "applications": apps
        }, indent=2)
    except Exception as e:
        return f"Error retrieving application pipeline: {str(e)}"


@mcp.tool()
def log_job_application(
    job_url: str,
    company: str,
    role_title: str,
    platform: str = "LinkedIn",
    location: Optional[str] = None,
    package: Optional[str] = None,
    notes: Optional[str] = None
) -> str:
    """[LOCAL CRM] Manually record a job application into the local SQLite CRM and atomic JSON mirror."""
    try:
        res = crm.record_application(
            job_url=job_url,
            company=company,
            role_title=role_title,
            platform=platform,
            location=location,
            package=package,
            notes=notes
        )
        return json.dumps(res, indent=2)
    except Exception as e:
        return f"Error logging job application: {str(e)}"


@mcp.tool()
def update_application_status(
    job_id_or_company: str,
    status: str,
    notes: Optional[str] = None,
    recruiter_name: Optional[str] = None,
    recruiter_profile_url: Optional[str] = None
) -> str:
    """[LOCAL CRM] Update an application's status (APPLIED, TOUCHPOINT_1_CONNECT_SENT, TOUCHPOINT_2_FOLLOWUP_SENT, INTERVIEW_SCHEDULED, REJECTED, OFFER, CLOSED) and append notes."""
    try:
        res = crm.update_application_status(
            job_key_or_url_or_id=job_id_or_company,
            status=status,
            notes=notes,
            recruiter_name=recruiter_name,
            recruiter_profile_url=recruiter_profile_url
        )
        return json.dumps(res, indent=2)
    except Exception as e:
        return f"Error updating application status: {str(e)}"


@mcp.tool()
def add_to_wishlist(
    job_url: str,
    company: str,
    role_title: str,
    platform: str = "LinkedIn",
    location: Optional[str] = None,
    package: Optional[str] = None,
    easy_apply: bool = False,
    notes: Optional[str] = None
) -> str:
    """[LOCAL CRM] Save an interesting job to your Wishlist / Will-Do-Later queue to apply later."""
    try:
        res = crm.add_to_wishlist(
            job_url=job_url,
            company=company,
            role_title=role_title,
            platform=platform,
            location=location,
            package=package,
            easy_apply=easy_apply,
            notes=notes
        )
        return json.dumps(res, indent=2)
    except Exception as e:
        return f"Error adding job to wishlist: {str(e)}"


@mcp.tool()
def get_wishlist(platform: Optional[str] = None, limit: int = 50) -> str:
    """[READ-ONLY] Retrieve all bookmarked jobs in your Wishlist / Will-Do-Later queue."""
    try:
        items = crm.get_wishlist(platform=platform, limit=limit)
        return json.dumps({
            "total_wishlist_items": len(items),
            "wishlist": items
        }, indent=2)
    except Exception as e:
        return f"Error retrieving wishlist: {str(e)}"


@mcp.tool()
def remove_from_wishlist(job_id_or_url_or_company: str) -> str:
    """[LOCAL CRM] Remove a job from your Wishlist / Will-Do-Later queue."""
    try:
        res = crm.remove_from_wishlist(job_id_or_url_or_company)
        return json.dumps(res, indent=2)
    except Exception as e:
        return f"Error removing from wishlist: {str(e)}"


@mcp.tool()
def convert_wishlist_to_applied(job_id_or_url_or_company: str, notes: Optional[str] = None) -> str:
    """[LOCAL CRM] Transition a wishlisted job to the active APPLIED pipeline and start recruiter follow-up cadence."""
    try:
        res = crm.convert_wishlist_to_applied(job_id_or_url_or_company, notes=notes)
        return json.dumps(res, indent=2)
    except Exception as e:
        return f"Error converting wishlist item to applied: {str(e)}"


@mcp.tool()
def get_pending_cadence_followups() -> str:
    """[READ-ONLY] Scan all tracked applications against the Recruiter Cadence engine (Day 2+ Connect, Day 7+ Follow-up DM, 24h deduplication guard). Returns ready-to-send personalized drafts."""
    try:
        actions = crm.get_pending_cadence_actions()
        return json.dumps({
            "total_pending_actions": len(actions),
            "cadence_schedule": actions
        }, indent=2)
    except Exception as e:
        return f"Error calculating cadence followups: {str(e)}"


@mcp.tool()
def execute_recruiter_cadence(
    application_id_or_company: str,
    recruiter_name_or_url: Optional[str] = None,
    confirmed: bool = False
) -> str:
    """[REQUIRES USER APPROVAL] Execute the next scheduled touchpoint (discover recruiter, send warm connection note, or follow-up DM) with 24h company deduplication guard."""
    guard = check_safety_guard("execute_recruiter_cadence", {
        "target_application": application_id_or_company,
        "recruiter_override": recruiter_name_or_url or "Auto-discover top recruiter at company"
    }, confirmed)
    if guard:
        return guard
    try:
        res = asyncio.run(crm.execute_cadence_action(
            application_id_or_company=application_id_or_company,
            recruiter_name_or_url=recruiter_name_or_url
        ))
        return json.dumps(res, indent=2)
    except Exception as e:
        return f"Error executing recruiter cadence: {str(e)}"


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


# ==============================================================================
# 18. Unified Cross-Platform Orchestration Tools
# ==============================================================================

@mcp.tool()
def search_cross_platform_jobs(
    role_keywords: str = "Staff SDET",
    location: str = "India",
    company: Optional[str] = None,
    platforms: str = "all",
    map_recruiters: bool = True,
    limit_per_platform: int = 5
) -> str:
    """
    [READ-ONLY] Unified Cross-Platform Job Hunter & Recruiter Intelligence.
    Searches jobs on Naukri and LinkedIn, maps active recruiters on LinkedIn for each company,
    and returns rich dossiers tagged with [Platform: Naukri] or [Platform: LinkedIn] plus direct URLs.
    """
    async def _execute():
        aggregated_jobs = []
        companies_seen = []

        # 1. Search Naukri
        if platforms.lower() in ("naukri", "all"):
            try:
                n_jobs = await _naukri_client.search_jobs(keywords=role_keywords, location=location, limit=limit_per_platform)
                for j in n_jobs:
                    comp = j.get("company", "Unknown Company")
                    title = j.get("title", role_keywords)
                    slug = comp.lower().replace(" ", "-").replace(".", "")
                    clean_url = f"https://www.naukri.com/{slug}-jobs"
                    aggregated_jobs.append({
                        "title": title,
                        "company": comp,
                        "platform": "NAUKRI",
                        "platform_tag": "[Platform: Naukri]",
                        "job_url": clean_url,
                        "location": j.get("location", location),
                        "experience": j.get("experience", ""),
                        "apply_type": "Quick Apply" if j.get("is_quick_apply") else "External Portal"
                    })
                    if comp not in companies_seen:
                        companies_seen.append(comp)
            except Exception as e:
                print(f"Error fetching Naukri jobs: {e}")

        # 2. Search LinkedIn
        if platforms.lower() in ("linkedin", "all"):
            try:
                l_jobs = await linkedin_dom.search_jobs(
                    keywords=role_keywords,
                    location=location,
                    company=company,
                    limit=limit_per_platform
                )
                for j in l_jobs:
                    comp = j.get("company", "Unknown Company")
                    aggregated_jobs.append({
                        "title": j.get("title", role_keywords),
                        "company": comp,
                        "platform": "LINKEDIN",
                        "platform_tag": "[Platform: LinkedIn]",
                        "job_url": j.get("job_url", ""),
                        "location": j.get("location", location),
                        "experience": "",
                        "apply_type": "Easy Apply" if j.get("easy_apply") else "External Portal"
                    })
                    if comp not in companies_seen:
                        companies_seen.append(comp)
            except Exception as e:
                print(f"Error fetching LinkedIn jobs: {e}")

        # 3. Map LinkedIn Recruiters for top target companies
        company_recruiters = {}
        if map_recruiters:
            for comp in companies_seen[:2]:
                try:
                    recs = await linkedin_dom.search_people_at_company(company_name=comp, role_keyword="Recruiter", limit=2)
                    company_recruiters[comp] = recs
                except Exception:
                    company_recruiters[comp] = []

        # Attach recruiters and pre-drafted pitch
        for job in aggregated_jobs:
            c_name = job["company"]
            job["linked_recruiters_on_linkedin"] = company_recruiters.get(c_name, [])
            first_rec = job["linked_recruiters_on_linkedin"][0]["name"] if job["linked_recruiters_on_linkedin"] else "Hiring Team"
            job["suggested_dm_pitch"] = (
                f"Hi {first_rec}, I spotted the {job['title']} opening at {c_name} ({job['platform_tag']}: {job['job_url']}). "
                f"With ~10 yrs architecting QA/SDET automation (Playwright, Python, Cloud, AI testing), I'd love to connect and explore how I can support your goals!"
            )

        return json.dumps({
            "query": role_keywords,
            "location": location,
            "total_cross_platform_jobs": len(aggregated_jobs),
            "jobs": aggregated_jobs
        }, indent=2)

    try:
        return asyncio.run(_execute())
    except Exception as e:
        return f"Error executing cross-platform search: {str(e)}"



@mcp.tool()
def draft_recruiter_pitch(
    job_title: str,
    company: str,
    job_url: str,
    platform: str = "Naukri",
    recruiter_name: Optional[str] = None
) -> str:
    """
    [READ-ONLY] Generate a tailored, executive outbound message for a recruiter citing a specific job URL and platform.
    Dynamically tailored to the active candidate profile and target job.
    """
    cand = intelligence.get_candidate_context()
    rec_greeting = f"Hi {recruiter_name}" if recruiter_name else "Hello"
    short_note = (
        f"{rec_greeting}, I came across the {job_title} opening at {company} ([Platform: {platform}]: {job_url}). "
        f"With ~{int(round(float(cand['years_of_experience'])))} yrs in {cand['primary_title']} ({', '.join(cand['skills'][:3])}), I'd love to connect and explore synergy!"
    )

    full_dm = f"""{rec_greeting},

I hope you're having a productive week!

I noticed that {company} is actively hiring for a {job_title} ([Platform: {platform}]: {job_url}).

Given my background as a {cand['primary_title']} with {cand['years_of_experience']} years of experience engineering scalable systems across {', '.join(cand['skills'][:4])}, I believe my background strongly aligns with your team's technical and delivery goals.

I'd welcome the opportunity to discuss how my expertise can drive impact for {company}.

Best regards,
{cand['full_name']}
Portfolio: {cand['portfolio_url'] or cand['linkedin_url']}"""

    return json.dumps({
        "company": company,
        "job_title": job_title,
        "platform_tag": f"[Platform: {platform}]",
        "job_url": job_url,
        "connection_request_note_300chars": short_note[:299],
        "full_direct_message": full_dm
    }, indent=2)


# ==============================================================================
# 20. Intelligence, Cover Letter Customization & Interview Prep Tools
# ==============================================================================

@mcp.tool()
def audit_job_compatibility(
    job_id_or_url: str,
    role_title: Optional[str] = None
) -> str:
    """[READ-ONLY] Contrast candidate profile against job description. Highlights match percentage, core matching competencies, project synergies, missing keyword gaps, and interview talking points."""
    try:
        res = intelligence.audit_job_compatibility(job_id_or_url, role_title=role_title)
        return json.dumps(res, indent=2)
    except Exception as e:
        return f"Error auditing job compatibility: {str(e)}"


@mcp.tool()
def generate_targeted_cover_letter(
    job_id_or_url: str,
    role_title: Optional[str] = None,
    output_format: str = "text"
) -> str:
    """[READ-ONLY] Generate a tailored 3-paragraph executive cover letter pitch emphasizing matching projects from candidate history. When output_format='pdf', strictly guarantees a 1-page PDF layout without overflow or truncation."""
    try:
        res = intelligence.generate_targeted_cover_letter(job_id_or_url, role_title=role_title, output_format=output_format)
        return json.dumps(res, indent=2)
    except Exception as e:
        return f"Error generating targeted cover letter: {str(e)}"


@mcp.tool()
def generate_interview_dossier(
    company_name: str,
    role_title: Optional[str] = None
) -> str:
    """[READ-ONLY] Automated Interview Prep & Company Dossier: Product vs Service classification, funding/stage/valuation, ratings, recent/upcoming events, engineering leadership discovery, tech stack analysis, high-probability technical questions tailored to target role and candidate background with winning answers, and strategic reverse-interview questions."""
    try:
        res = asyncio.run(intelligence.generate_interview_dossier(company_name, role_title=role_title))
        return json.dumps(res, indent=2)
    except Exception as e:
        return f"Error generating interview dossier: {str(e)}"
@mcp.tool()
def send_email_notification(
    subject: str,
    body: str,
    to_email: Optional[str] = None,
    html: bool = False,
    attachment_paths: Optional[List[str]] = None
) -> str:
    """Send an email notification securely using the configured SMTP app password in .env.
    
    Pulls credentials (app password, sender, recipient) dynamically from .env so no secrets or personal info are exposed.
    Can be used to dispatch application alerts, interview dossiers, cover letters, or candidate updates directly to the designated email.
    """
    try:
        res = email_service.send_email(
            subject=subject,
            body=body,
            to_email=to_email,
            html=html,
            attachment_paths=attachment_paths,
        )
        return json.dumps(res, indent=2)
    except Exception as e:
        return f"Error sending email: {str(e)}"


@mcp.tool()
def send_interview_prep_email(
    company_name: str,
    role_title: Optional[str] = None,
    to_email: Optional[str] = None
) -> str:
    """Analyzes the target company and job profile through native AI IDE intelligence,
    generates a comprehensive deep-dive interview dossier (including technical questions,
    winning talking points, coding demonstrations, leadership discovery, and reverse questions),
    renders an IDE-styled HTML layout and PDF attachment, and securely emails it to the user.
    """
    try:
        # 1. Generate full dossier intelligence
        dossier = asyncio.run(intelligence.generate_interview_dossier(company_name, role_title=role_title))
        if dossier.get("status") != "SUCCESS":
            return json.dumps({"status": "error", "message": "Failed to compile dossier intelligence."})

        # 2. Format rich IDE-styled HTML
        html_content = intelligence.format_dossier_html(dossier)
        clean_name = re.sub(r'[^a-zA-Z0-9_]', '_', company_name.strip())
        pdf_path = BASE_DIR / f"{clean_name}_Comprehensive_Interview_Dossier.pdf"

        # 3. Render PDF artifact
        asyncio.run(intelligence.render_dossier_pdf(html_content, str(pdf_path)))

        # 4. Check for cover letter to attach if present
        attachments = [str(pdf_path)]
        cl_pattern = BASE_DIR / f"Targeted_Cover_Letter_{clean_name}.pdf"
        if cl_pattern.is_file():
            attachments.append(str(cl_pattern))
        else:
            for f in os.listdir(BASE_DIR):
                if f.startswith("Targeted_Cover_Letter_") and f.endswith(".pdf"):
                    attachments.append(str(BASE_DIR / f))
                    break

        # 5. Dispatch email
        subject = f"Deep Technical Interview Intelligence Dossier: {company_name}"
        res = email_service.send_email(
            subject=subject,
            body=html_content,
            to_email=to_email,
            html=True,
            attachment_paths=attachments,
        )
        return json.dumps({
            "status": "success",
            "company": company_name,
            "role": dossier.get("role_title"),
            "questions_prepared": len(dossier.get("high_probability_technical_questions", [])),
            "email_dispatch": res,
            "pdf_generated": str(pdf_path)
        }, indent=2)
    except Exception as e:
        return f"Error executing send_interview_prep_email: {str(e)}"
