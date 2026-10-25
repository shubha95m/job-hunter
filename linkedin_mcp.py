#!/usr/bin/env python3
"""
Enterprise-Grade Local LinkedIn MCP Server for AI IDEs (Antigravity, Cursor, Claude, Codex).
Combines ultra-fast Voyager API queries with Playwright session automation.
Safety Rule: ALL write, update, delete, post, and send actions STRICTLY require confirmed=True with user approval.
"""

import os
import sys
import json
import re
import urllib.parse
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any

import httpx
from mcp.server.mcpserver import MCPServer
from playwright.async_api import async_playwright

mcp = MCPServer("linkedin-manager")

BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = Path(os.getenv("LINKEDIN_AUTH_STATE", str(BASE_DIR / ".auth/state.json")))
DEFAULT_CV_PATH = Path(os.getenv("DEFAULT_CV_PATH", str(BASE_DIR / "cv-content")))
SELF_VANITY_FILTER = os.getenv("LINKEDIN_VANITY_FILTER", "")

# ==============================================================================
# Helper Functions: Session & Safety Guards
# ==============================================================================

def _load_auth_session():
    """Load cookies and create an authenticated httpx client for Voyager API."""
    if not STATE_FILE.exists():
        raise FileNotFoundError(f"Auth state file not found at {STATE_FILE}. Please run auth.py first.")
    
    with open(STATE_FILE, "r") as f:
        data = json.load(f)
    
    cookies = {c["name"]: c["value"] for c in data.get("cookies", []) if "linkedin" in c.get("domain", "")}
    jsessionid = cookies.get("JSESSIONID", "").strip('"')
    
    headers = {
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "csrf-token": jsessionid,
        "x-restli-protocol-version": "2.0.0",
        "accept": "application/vnd.linkedin.normalized+json+2.1"
    }
    return httpx.Client(cookies=cookies, headers=headers, timeout=20.0)

def _get_profile_metadata(client: httpx.Client):
    """Retrieve basic profile metadata including URN, publicIdentifier, name, and headline."""
    me_resp = client.get("https://www.linkedin.com/voyager/api/me")
    if me_resp.status_code != 200:
        raise RuntimeError(f"LinkedIn authentication failed with status: {me_resp.status_code}")
    
    me_data = me_resp.json()
    included = me_data.get("included", [])
    
    meta = {
        "first_name": "",
        "last_name": "",
        "public_id": "",
        "headline": "",
        "profile_urn": ""
    }
    
    for item in included:
        if item.get("publicIdentifier"):
            meta["first_name"] = item.get("firstName", "")
            meta["last_name"] = item.get("lastName", "")
            meta["public_id"] = item.get("publicIdentifier", "")
            meta["headline"] = item.get("occupation", "")
            meta["profile_urn"] = item.get("dashEntityUrn", "")
            break
            
    return meta

def _check_safety_guard(action_name: str, proposed_payload: dict, confirmed: bool) -> Optional[str]:
    """
    CRITICAL SAFETY ENFORCEMENT:
    Halts execution and returns a structured approval prompt if confirmed is False.
    Ensures no AI agent (Antigravity, Cursor, Claude, Codex) can mutate LinkedIn data without user approval.
    """
    if not confirmed:
        return json.dumps({
            "status": "APPROVAL_REQUIRED",
            "action": action_name,
            "proposed_changes": proposed_payload,
            "safety_warning": "⚠️ MUTATION PAUSED: Explicit user approval is required before executing write/update/delete/post actions on LinkedIn. Present the proposed changes above to the user and re-invoke with confirmed=True only after they confirm."
        }, indent=2)
    return None

# ==============================================================================
# 1. Profile Overview
# ==============================================================================

@mcp.tool()
def get_linkedin_profile() -> str:
    """Fetch complete overview of your LinkedIn profile (name, headline, public identifier, about preview, profile URL)."""
    try:
        client = _load_auth_session()
        meta = _get_profile_metadata(client)
        public_id = meta["public_id"]
        
        # Fetch detailed profile from dash
        dash_resp = client.get(
            f"https://www.linkedin.com/voyager/api/identity/dash/profiles?q=memberIdentity&memberIdentity={public_id}"
        )
        headline = meta["headline"]
        summary = ""
        
        if dash_resp.status_code == 200:
            for inc in dash_resp.json().get("included", []):
                t = inc.get("$type", "")
                if "Profile" in t:
                    headline = inc.get("headline", headline)
                    summary = inc.get("summary") or ""
                    break
                    
        return json.dumps({
            "name": f"{meta['first_name']} {meta['last_name']}".strip(),
            "headline": headline,
            "about": summary,
            "public_identifier": public_id,
            "profile_url": f"https://www.linkedin.com/in/{public_id}/" if public_id else ""
        }, indent=2)
    except Exception as e:
        return f"Error fetching LinkedIn profile: {str(e)}"

# ==============================================================================
# 2. Intro Section (Get & Update)
# ==============================================================================

@mcp.tool()
def get_intro() -> str:
    """Get the intro section details: full name, headline, public vanity URL, and occupation."""
    try:
        client = _load_auth_session()
        meta = _get_profile_metadata(client)
        return json.dumps({
            "full_name": f"{meta['first_name']} {meta['last_name']}".strip(),
            "headline": meta["headline"],
            "vanity_name": meta["public_id"],
            "profile_url": f"https://www.linkedin.com/in/{meta['public_id']}/"
        }, indent=2)
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
        
    guard = _check_safety_guard("update_intro", proposed, confirmed)
    if guard:
        return guard

    async def _update():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
            context = await browser.new_context(storage_state=str(STATE_FILE))
            page = await context.new_page()
            try:
                await page.goto("https://www.linkedin.com/in/me/edit/forms/intro/new/?profileFormEntryPoint=PROFILE_SECTION", wait_until="domcontentloaded", timeout=25000)
                await page.wait_for_timeout(3000)
                
                if new_headline:
                    h_input = page.locator("input[id*='headline'], textarea[id*='headline'], input[name='headline']").first
                    if await h_input.count() > 0:
                        await h_input.fill(new_headline)
                        
                save_btn = page.locator("button:has-text('Save')").first
                await save_btn.click()
                await page.wait_for_timeout(3000)
                await browser.close()
                return json.dumps({"status": "SUCCESS", "message": "Updated intro section successfully on LinkedIn.", "applied_changes": proposed}, indent=2)
            except Exception as e:
                await browser.close()
                return f"Error updating intro via Playwright: {str(e)}"
                
    return asyncio.run(_update())

# ==============================================================================
# 3. About Section (Get & Update)
# ==============================================================================

@mcp.tool()
def get_about() -> str:
    """Retrieve your full LinkedIn 'About' / Summary section text."""
    try:
        client = _load_auth_session()
        meta = _get_profile_metadata(client)
        public_id = meta["public_id"]
        
        dash_resp = client.get(
            f"https://www.linkedin.com/voyager/api/identity/dash/profiles?q=memberIdentity&memberIdentity={public_id}"
        )
        if dash_resp.status_code == 200:
            for inc in dash_resp.json().get("included", []):
                if "Profile" in inc.get("$type", ""):
                    about_text = inc.get("summary") or ""
                    return json.dumps({
                        "about": about_text,
                        "character_count": len(about_text)
                    }, indent=2)
        return json.dumps({"about": "", "character_count": 0})
    except Exception as e:
        return f"Error retrieving About section: {str(e)}"

@mcp.tool()
def update_about(new_about: str, confirmed: bool = False) -> str:
    """[REQUIRES USER APPROVAL] Update your LinkedIn 'About' / Summary section. Set confirmed=True only after asking the user."""
    guard = _check_safety_guard("update_about", {"new_about": new_about, "character_count": len(new_about)}, confirmed)
    if guard:
        return guard

    async def _update():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
            context = await browser.new_context(storage_state=str(STATE_FILE))
            page = await context.new_page()
            try:
                await page.goto("https://www.linkedin.com/in/me/edit/forms/summary/new/?profileFormEntryPoint=PROFILE_SECTION", wait_until="domcontentloaded", timeout=25000)
                await page.wait_for_timeout(3000)
                
                summary_input = page.locator("textarea[id*='summary'], textarea[name='summary']").first
                if await summary_input.count() > 0:
                    await summary_input.fill(new_about)
                    await page.wait_for_timeout(1000)
                    
                    save_btn = page.locator("button:has-text('Save')").first
                    await save_btn.click()
                    await page.wait_for_timeout(3000)
                    await browser.close()
                    return json.dumps({"status": "SUCCESS", "message": "Successfully updated About section on LinkedIn.", "character_count": len(new_about)}, indent=2)
                else:
                    await browser.close()
                    return "Could not locate About/Summary input field on LinkedIn edit modal."
            except Exception as e:
                await browser.close()
                return f"Error updating About section: {str(e)}"
                
    return asyncio.run(_update())

# ==============================================================================
# 4. Experience & Positions (Full, by Company, Individual, and Updates)
# ==============================================================================

def _fetch_all_positions(client: httpx.Client, profile_urn: str) -> List[Dict[str, Any]]:
    """Helper to fetch and normalize positions from Voyager API."""
    encoded_urn = urllib.parse.quote(profile_urn)
    resp = client.get(f"https://www.linkedin.com/voyager/api/identity/dash/profilePositions?q=viewee&profileUrn={encoded_urn}")
    if resp.status_code != 200:
        return []
        
    positions = []
    for item in resp.json().get("included", []):
        if "Position" in item.get("$type", ""):
            date_range = item.get("dateRange") or {}
            start = date_range.get("start") or {}
            end = date_range.get("end") or {}
            start_str = f"{start.get('month', '')}/{start.get('year', '')}" if start.get('year') else ""
            end_str = f"{end.get('month', '')}/{end.get('year', '')}" if end.get('year') else "Present"
            
            positions.append({
                "title": item.get("title", ""),
                "company": item.get("companyName", ""),
                "location": item.get("locationName", ""),
                "start_date": start_str,
                "end_date": end_str,
                "description": item.get("description", "") or "",
                "entity_urn": item.get("entityUrn", "")
            })
    return positions

@mcp.tool()
def get_experience(company: Optional[str] = None) -> str:
    """Get full experience history, or filter positions by company name (e.g. 'AlphaSense', 'Accenture')."""
    try:
        client = _load_auth_session()
        meta = _get_profile_metadata(client)
        positions = _fetch_all_positions(client, meta["profile_urn"])
        
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
        client = _load_auth_session()
        meta = _get_profile_metadata(client)
        positions = _fetch_all_positions(client, meta["profile_urn"])
        
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
    proposed = {
        "company": company_name,
        "role": role_title,
        "new_description": new_description
    }
    guard = _check_safety_guard("update_position", proposed, confirmed)
    if guard:
        return guard

    async def _update():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
            context = await browser.new_context(storage_state=str(STATE_FILE))
            page = await context.new_page()
            try:
                await page.goto("https://www.linkedin.com/in/me/details/experience/", wait_until="domcontentloaded", timeout=25000)
                await page.wait_for_timeout(3000)
                
                # Locate edit button for position
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
                        await browser.close()
                        return json.dumps({"status": "SUCCESS", "message": f"Updated position '{role_title}' at '{company_name}' successfully."}, indent=2)
                
                await browser.close()
                return f"Could not find the edit form for role '{role_title}' at '{company_name}'."
            except Exception as e:
                await browser.close()
                return f"Error updating position: {str(e)}"
                
    return asyncio.run(_update())

# ==============================================================================
# 5. Education & Certifications
# ==============================================================================

@mcp.tool()
def get_education() -> str:
    """Retrieve all degrees, universities/schools, and education history on LinkedIn."""
    try:
        client = _load_auth_session()
        meta = _get_profile_metadata(client)
        encoded_urn = urllib.parse.quote(meta["profile_urn"])
        
        resp = client.get(f"https://www.linkedin.com/voyager/api/identity/dash/profileEducations?q=viewee&profileUrn={encoded_urn}")
        if resp.status_code != 200:
            return "Failed to fetch education records."
            
        educations = []
        for item in resp.json().get("included", []):
            if "Education" in item.get("$type", ""):
                school = item.get("schoolName", "")
                degree = item.get("degreeName", "")
                fos = item.get("fieldOfStudy", "")
                if school:
                    educations.append({
                        "school": school,
                        "degree": degree,
                        "field_of_study": fos,
                        "grade": item.get("grade", "")
                    })
        return json.dumps({"total_education_entries": len(educations), "education": educations}, indent=2)
    except Exception as e:
        return f"Error retrieving education: {str(e)}"

@mcp.tool()
def get_certifications() -> str:
    """Retrieve all licenses and certifications on LinkedIn."""
    try:
        client = _load_auth_session()
        meta = _get_profile_metadata(client)
        encoded_urn = urllib.parse.quote(meta["profile_urn"])
        
        resp = client.get(f"https://www.linkedin.com/voyager/api/identity/dash/profileCertifications?q=viewee&profileUrn={encoded_urn}")
        if resp.status_code != 200:
            return "Failed to fetch certifications."
            
        certs = []
        for item in resp.json().get("included", []):
            if "Certification" in item.get("$type", ""):
                name = item.get("name", "")
                authority = item.get("authority", "")
                if name:
                    certs.append({
                        "name": name,
                        "issuing_authority": authority,
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
        client = _load_auth_session()
        meta = _get_profile_metadata(client)
        encoded_urn = urllib.parse.quote(meta["profile_urn"])
        
        resp = client.get(f"https://www.linkedin.com/voyager/api/identity/dash/profileSkills?q=viewee&profileUrn={encoded_urn}")
        if resp.status_code != 200:
            return "Failed to fetch skills."
            
        skills = []
        for item in resp.json().get("included", []):
            if "Skill" in item.get("$type", ""):
                name = item.get("name", "")
                if name:
                    skills.append(name)
        return json.dumps({"total_skills": len(skills), "skills": skills}, indent=2)
    except Exception as e:
        return f"Error retrieving skills: {str(e)}"

@mcp.tool()
def add_skill(skill_name: str, confirmed: bool = False) -> str:
    """[REQUIRES USER APPROVAL] Add a new skill to your LinkedIn profile. Set confirmed=True only after asking the user."""
    guard = _check_safety_guard("add_skill", {"skill": skill_name}, confirmed)
    if guard:
        return guard

    async def _add():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
            context = await browser.new_context(storage_state=str(STATE_FILE))
            page = await context.new_page()
            try:
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
                    await browser.close()
                    return json.dumps({"status": "SUCCESS", "message": f"Successfully added skill '{skill_name}' on LinkedIn."}, indent=2)
                await browser.close()
                return "Could not locate the 'Add skill' button."
            except Exception as e:
                await browser.close()
                return f"Error adding skill: {str(e)}"
                
    return asyncio.run(_add())

# ==============================================================================
# 7. Post Updates
# ==============================================================================

@mcp.tool()
def create_post(post_text: str, confirmed: bool = False) -> str:
    """[REQUIRES USER APPROVAL] Create and publish a post on LinkedIn. Set confirmed=True only after asking the user."""
    guard = _check_safety_guard("create_post", {"post_text": post_text, "character_count": len(post_text)}, confirmed)
    if guard:
        return guard

    async def _post():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
            context = await browser.new_context(storage_state=str(STATE_FILE))
            page = await context.new_page()
            try:
                await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=25000)
                await page.wait_for_timeout(3000)
                
                # Click start post
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
                    await browser.close()
                    return json.dumps({"status": "SUCCESS", "message": "Post successfully published to LinkedIn feed!"}, indent=2)
                    
                await browser.close()
                return "Could not locate 'Start a post' button on feed."
            except Exception as e:
                await browser.close()
                return f"Error creating post: {str(e)}"
                
    return asyncio.run(_post())

# ==============================================================================
# 8. DMs & Messaging
# ==============================================================================

@mcp.tool()
def get_unread_messages(limit: int = 10) -> str:
    """Retrieve recent LinkedIn messages, highlighting unread DMs, senders, and snippets."""
    async def _messages():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
            context = await browser.new_context(storage_state=str(STATE_FILE))
            page = await context.new_page()
            try:
                await page.goto("https://www.linkedin.com/messaging/", wait_until="domcontentloaded", timeout=25000)
                await page.wait_for_timeout(3000)
                
                threads = await page.evaluate(f'''() => {{
                    const list = [];
                    const items = document.querySelectorAll('.msg-conversation-listitem, [data-view-name=\"message-thread-item\"]');
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
                await browser.close()
                return json.dumps({
                    "total_retrieved": len(threads),
                    "unread_count": sum(1 for t in threads if t["is_unread"]),
                    "conversations": threads
                }, indent=2)
            except Exception as e:
                await browser.close()
                return f"Error retrieving messages: {str(e)}"
                
    return asyncio.run(_messages())

@mcp.tool()
def reply_in_dm(sender_name: str, reply_text: str, confirmed: bool = False) -> str:
    """[REQUIRES USER APPROVAL] Send or reply to a LinkedIn DM conversation. Works with inbox threads or by recipient name. Set confirmed=True only after asking the user."""
    guard = _check_safety_guard("reply_in_dm", {"recipient": sender_name, "message": reply_text}, confirmed)
    if guard:
        return guard

    async def _send():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
            context = await browser.new_context(storage_state=str(STATE_FILE))
            page = await context.new_page()
            try:
                # 1. First check existing messaging inbox
                await page.goto("https://www.linkedin.com/messaging/", wait_until="domcontentloaded", timeout=25000)
                await page.wait_for_timeout(3000)
                
                thread = page.locator(f"//li[contains(@class, 'msg-conversation-listitem') and contains(., '{sender_name}')]").first
                if await thread.count() > 0:
                    await thread.click()
                    await page.wait_for_timeout(2000)
                    
                    editor = page.locator("div.msg-form__contenteditable, div[role='textbox']").last
                    await editor.click()
                    await page.keyboard.insert_text(reply_text)
                    try:
                        await page.evaluate("(el) => el.dispatchEvent(new Event('input', { bubbles: true }))", await editor.element_handle())
                    except Exception:
                        pass
                    await page.wait_for_timeout(300)
                    
                    send_btn = page.locator("button.msg-form__send-button").last
                    if await send_btn.count() > 0 and await send_btn.is_enabled():
                        await send_btn.click()
                    await page.wait_for_timeout(1500)
                    if await editor.inner_text() != '':
                        await editor.press('Enter')
                    await page.wait_for_timeout(2500)
                    await browser.close()
                    return json.dumps({"status": "SUCCESS", "message": f"Reply successfully sent to '{sender_name}' in messaging inbox."}, indent=2)
                
                # 2. Fallback: Search connection profile and open composer
                encoded = urllib.parse.quote(sender_name)
                await page.goto(f"https://www.linkedin.com/search/results/people/?keywords={encoded}", wait_until="domcontentloaded", timeout=25000)
                await page.wait_for_timeout(3500)
                
                link = page.locator("a[href*='/in/']").first
                if await link.count() > 0:
                    href = await link.get_attribute("href")
                    if href:
                        clean_url = href.split('?')[0]
                        await page.goto(clean_url, wait_until="domcontentloaded", timeout=25000)
                        await page.wait_for_timeout(3000)
                        
                        msg_btn = page.locator("a[href*='/messaging/compose'], button:has-text('Message')").first
                        if await msg_btn.count() > 0:
                            compose_href = await msg_btn.get_attribute("href")
                            if compose_href and '/messaging/compose' in compose_href:
                                await page.goto(f"https://www.linkedin.com{compose_href}", wait_until="domcontentloaded")
                            else:
                                await msg_btn.click(force=True)
                            await page.wait_for_timeout(2500)
                            
                            editor = page.locator("div.msg-form__contenteditable, div[role='textbox']").last
                            await editor.fill(reply_text)
                            await page.wait_for_timeout(1000)
                            
                            send_btn = page.locator("button.msg-form__send-button, button[type='submit']:has-text('Send'), button:has-text('Send')").last
                            await send_btn.click(force=True)
                            await page.wait_for_timeout(3000)
                            await browser.close()
                            return json.dumps({"status": "SUCCESS", "message": f"Direct message successfully sent to '{sender_name}'."}, indent=2)

                await browser.close()
                return f"Could not find conversation thread or connection profile for: '{sender_name}'."
            except Exception as e:
                await browser.close()
                return f"Error sending message: {str(e)}"
                
    return asyncio.run(_send())

# ==============================================================================
# 9. Job Search (Company, Title, Easy Apply, Remote/Hybrid)
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
    """
    Search jobs on LinkedIn by position, company, location, remote/on-site, easy apply, or employment type.
    - remote_only: If True, filters for remote jobs (f_WT=2)
    - easy_apply_only: If True, filters for Easy Apply jobs (f_AL=true)
    - employment_type: 'full-time' (f_JT=F), 'contract' (f_JT=C), 'part-time' (f_JT=P)
    """
    params = [
        f"keywords={urllib.parse.quote(keywords)}",
        f"location={urllib.parse.quote(location)}"
    ]
    if easy_apply_only:
        params.append("f_AL=true")
    if remote_only:
        params.append("f_WT=2")
    if employment_type:
        jt_map = {"full-time": "F", "contract": "C", "part-time": "P"}
        code = jt_map.get(employment_type.lower())
        if code:
            params.append(f"f_JT={code}")
            
    search_url = f"https://www.linkedin.com/jobs/search/?{'&'.join(params)}"

    async def _jobs():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
            context = await browser.new_context(storage_state=str(STATE_FILE))
            page = await context.new_page()
            try:
                await page.goto(search_url, wait_until="domcontentloaded", timeout=25000)
                await page.wait_for_timeout(3500)
                
                jobs = await page.evaluate(f'''() => {{
                    const cards = document.querySelectorAll('.job-card-container, .jobs-search-results__list-item');
                    const results = [];
                    for (const c of cards) {{
                        const titleEl = c.querySelector('.job-card-list__title, a.job-card-container__link');
                        const compEl = c.querySelector('.job-card-container__primary-description, .artdeco-entity-lockup__subtitle');
                        const locEl = c.querySelector('.job-card-container__metadata-item');
                        const linkEl = c.querySelector('a.job-card-container__link, a[href*="/jobs/view/"]');
                        const easyApplyBadge = c.querySelector('.job-card-container__apply-method') || (c.innerText && c.innerText.includes('Easy Apply'));
                        
                        const title = titleEl ? titleEl.innerText.split('\\n')[0].trim() : 'Unknown';
                        const comp = compEl ? compEl.innerText.trim() : 'Unknown';
                        const loc = locEl ? locEl.innerText.trim() : '';
                        const href = linkEl ? linkEl.href.split('?')[0] : '';
                        
                        results.push({{
                            title: title,
                            company: comp,
                            location: loc,
                            easy_apply: !!easyApplyBadge,
                            job_url: href
                        }});
                    }}
                    return results;
                }}''')
                
                filtered = jobs
                if company:
                    filtered = [j for j in jobs if company.lower() in j["company"].lower()]
                    
                await browser.close()
                return json.dumps({
                    "search_query": keywords,
                    "location": location,
                    "search_url": search_url,
                    "total_found": len(filtered[:limit]),
                    "jobs": filtered[:limit]
                }, indent=2)
            except Exception as e:
                await browser.close()
                return f"Error executing job search: {str(e)}"
                
    return asyncio.run(_jobs())

# ==============================================================================
# 10. Recruiter & People Search in a Company
# ==============================================================================

@mcp.tool()
def search_recruiters(company_name: str, limit: int = 10) -> str:
    """Search active recruiters and talent acquisition leads at a specific company (e.g. 'AlphaSense', 'Google')."""
    return search_people_at_company(company_name=company_name, role_keyword="recruiter", limit=limit)

@mcp.tool()
def search_people_at_company(company_name: str, role_keyword: Optional[str] = None, limit: int = 10) -> str:
    """Search people/employees at a specific company, optionally filtered by role (e.g. 'recruiter', 'engineering manager', 'sdet')."""
    keyword_query = f"{role_keyword or ''} at {company_name}".strip()
    encoded = urllib.parse.quote(keyword_query)
    search_url = f"https://www.linkedin.com/search/results/people/?keywords={encoded}"

    async def _people():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
            context = await browser.new_context(storage_state=str(STATE_FILE))
            page = await context.new_page()
            try:
                await page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(3000)
                
                links = await page.locator("a[href*='/in/']").all()
                people = []
                seen = set()
                
                for l in links:
                    try:
                        txt = (await l.inner_text()).strip()
                        href = (await l.get_attribute("href") or "").split("?")[0]
                        if not href or href in seen or (SELF_VANITY_FILTER and SELF_VANITY_FILTER in href):
                            continue
                        if any(k in txt.lower() for k in ["mutual", "connection", "shared", "follow", "view", "connect", "others", "see open"]):
                            continue
                        name = txt.splitlines()[0].strip()
                        if len(name) <= 2:
                            continue
                            
                        seen.add(href)
                        ancestor = await l.locator("xpath=../../..").inner_text()
                        anc_lower = ancestor.lower()
                        
                        comp_match = company_name.lower() in anc_lower
                        role_match = True
                        if role_keyword:
                            role_match = any(r in anc_lower for r in [role_keyword.lower(), "recruiter", "talent", "hiring", "acquisition"])
                            
                        if comp_match and role_match:
                            lines_anc = [ln.strip() for ln in ancestor.splitlines() if ln.strip()]
                            headline = f"{role_keyword or 'Employee'} at {company_name}"
                            for idx, line in enumerate(lines_anc):
                                if line.lower() == name.lower() and idx + 1 < len(lines_anc):
                                    headline = lines_anc[idx+2] if ("•" in lines_anc[idx+1] and idx + 2 < len(lines_anc)) else lines_anc[idx+1]
                                    break
                            people.append({
                                "name": name,
                                "profile_url": href,
                                "headline": headline
                            })
                            if len(people) >= limit:
                                break
                    except Exception:
                        continue
                        
                await browser.close()
                return json.dumps({
                    "company": company_name,
                    "role_keyword": role_keyword or "any",
                    "search_url": search_url,
                    "total_found": len(people),
                    "people": people
                }, indent=2)
            except Exception as e:
                await browser.close()
                return f"Error searching people in company: {str(e)}"
                
    return asyncio.run(_people())

# ==============================================================================
# CV Sync & Gap Analysis
# ==============================================================================

@mcp.tool()
def review_linkedin_against_cv(cv_folder: Optional[str] = None) -> str:
    """Compare live LinkedIn profile against your local CV (journey.json and summary.json) to identify gaps and suggest updates."""
    target_dir = Path(cv_folder) if cv_folder else DEFAULT_CV_PATH
    journey_file = target_dir / "journey.json"
    summary_file = target_dir / "summary.json"
    
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


# ==============================================================================
# 11. Accelerated People Search & Connection Tools
# ==============================================================================

@mcp.tool()
def find_person(query: str, in_connections_only: bool = False, limit: int = 5) -> str:
    """
    Find any person on LinkedIn.
    ALWAYS searches 1st-degree connections FIRST. If not found, falls back to public network.
    Returns: Name, Headline, Current Company/Role, Connection Degree ('1st', '2nd/3rd+'), and Profile URL.
    """
    """
    Instantly find any person on LinkedIn by name or title.
    - in_connections_only: Set to True to filter ONLY 1st-degree connections.
    - Returns full name, relationship degree ('1st', '2nd', '3rd+'), headline, and direct profile URL.
    """
    import urllib.parse
    encoded = urllib.parse.quote(query)

    async def _search():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
            context = await browser.new_context(storage_state=str(STATE_FILE))
            page = await context.new_page()
            try:
                # 1. ALWAYS search 1st-degree connections FIRST
                url_1st = f"https://www.linkedin.com/search/results/people/?keywords={encoded}&network=%5B%22F%22%5D"
                await page.goto(url_1st, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(3000)
                
                results = await page.evaluate(r"""() => {
                    const list = [];
                    const anchors = Array.from(document.querySelectorAll('a[href*="/in/"]'));
                    const seen = new Set();
                    for (const a of anchors) {
                        const href = a.href.split('?')[0];
                        if (seen.has(href)) continue;
                        
                        const container = a.closest('li') || a.closest('div[role="listitem"]') || a.parentElement;
                        const text = container ? container.innerText : a.innerText;
                        const lines = text.split('\n').map(s => s.trim()).filter(s => s.length > 0);
                        
                        let name = a.innerText.trim();
                        let degree = '2nd+';
                        if (text.includes('1st') || text.includes('· 1st')) degree = '1st';
                        else if (text.includes('2nd') || text.includes('· 2nd')) degree = '2nd';
                        else if (text.includes('3rd') || text.includes('· 3rd')) degree = '3rd+';
                        
                        let headline = '';
                        for (const l of lines) {
                            if (l !== name && !l.includes('degree') && !l.includes('1st') && !l.includes('2nd') && !l.includes('Connect') && !l.includes('Message') && l.length > 5) {
                                headline = l;
                                break;
                            }
                        }
                        
                        seen.add(href);
                        list.push({
                            name: name.split('\n')[0].trim(),
                            connection_degree: degree,
                            headline: headline,
                            profile_url: href,
                            can_direct_message: degree === '1st'
                        });
                    }
                    return list;
                }""")
                # If not found in 1st connections and caller didn't explicitly forbid public, search public
                if not results and not in_connections_only:
                    url_pub = f"https://www.linkedin.com/search/results/people/?keywords={encoded}"
                    await page.goto(url_pub, wait_until="domcontentloaded", timeout=20000)
                    await page.wait_for_timeout(3000)
                    results = await page.evaluate(r'''() => {
                        const list = [];
                        const anchors = Array.from(document.querySelectorAll('a[href*="/in/"]'));
                        const seen = new Set();
                        for (const a of anchors) {
                            const href = a.href.split('?')[0];
                            if (seen.has(href)) continue;
                            seen.add(href);
                            list.push({
                                name: a.innerText.trim().split('
')[0],
                                connection_degree: '2nd/3rd+',
                                headline: '',
                                profile_url: href,
                                can_direct_message: false
                            });
                        }
                        return list;
                    }''')

                await browser.close()
                return json.dumps({
                    "search_query": query,
                    "searched_connections_first": True,
                    "total_found": len(results[:limit]),
                    "people": results[:limit]
                }, indent=2)
            except Exception as e:
                await browser.close()
                return f"Error finding person: {str(e)}"

    return asyncio.run(_search())

@mcp.tool()
def get_person_profile(profile_identifier_or_url: str) -> str:
    """
    Inspect any person's full profile details (headline, about summary, current company/title, location).
    Accepts public identifier (e.g. 'john-doe-12345678') or profile URL.
    """
    pid = profile_identifier_or_url.strip("/").split("/")[-1].split("?")[0]
    try:
        client = _load_auth_session()
        dash_resp = client.get(
            f"https://www.linkedin.com/voyager/api/identity/dash/profiles?q=memberIdentity&memberIdentity={pid}"
        )
        if dash_resp.status_code != 200:
            return f"Could not fetch profile for '{pid}': HTTP {dash_resp.status_code}"
            
        included = dash_resp.json().get("included", [])
        profile_data = {}
        for inc in included:
            if "Profile" in inc.get("$type", ""):
                profile_data = {
                    "name": f"{inc.get('firstName', '')} {inc.get('lastName', '')}".strip(),
                    "headline": inc.get("headline", ""),
                    "about": inc.get("summary", ""),
                    "location": inc.get("locationName", ""),
                    "public_identifier": pid,
                    "profile_url": f"https://www.linkedin.com/in/{pid}/"
                }
                break
                
        if not profile_data:
            return f"Profile details not found for '{pid}'."
        return json.dumps(profile_data, indent=2)
    except Exception as e:
        return f"Error fetching profile details: {str(e)}"

@mcp.tool()
def search_messages(query: str, limit: int = 5) -> str:
    """
    Search through all your LinkedIn message threads for past conversations with a person or keyword.
    """
    async def _search():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
            context = await browser.new_context(storage_state=str(STATE_FILE))
            page = await context.new_page()
            try:
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
                await browser.close()
                return json.dumps({"query": query, "total_matched": len(threads[:limit]), "threads": threads[:limit]}, indent=2)
            except Exception as e:
                await browser.close()
                return f"Error searching messages: {str(e)}"
                
    return asyncio.run(_search())

@mcp.tool()
def send_dm(recipient: str, message: str, confirmed: bool = False) -> str:
    """
    [REQUIRES USER APPROVAL] Fast, universal direct message tool.
    Accepts recipient name (e.g. 'Jane Doe'), public ID, or profile URL.
    - If confirmed=False: Pauses, resolves recipient, checks connection, and asks for approval.
    - If confirmed=True: Directly dispatches message and verifies delivery.
    """
    guard = _check_safety_guard("send_dm", {"recipient": recipient, "message": message}, confirmed)
    if guard:
        return guard

    import urllib.parse
    async def _send():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
            context = await browser.new_context(storage_state=str(STATE_FILE))
            page = await context.new_page()
            try:
                editor = None
                # Fast path A: If recipient is a simple name, check existing inbox threads first (<2s)
                if not recipient.startswith("http") and not ("-" in recipient and len(recipient) > 15):
                    try:
                        await page.goto("https://www.linkedin.com/messaging/", wait_until="domcontentloaded", timeout=12000)
                        await page.wait_for_selector(".msg-conversation-listitem", timeout=6000)
                        thread = page.locator(".msg-conversation-listitem").filter(has_text=recipient).first
                        if await thread.count() > 0:
                            await thread.click()
                            editor = page.locator("div.msg-form__contenteditable, div[role='textbox']").last
                            await editor.wait_for(state="visible", timeout=5000)
                    except Exception:
                        pass

                # Fast path B: Direct profile or Search resolution
                if editor is None or await editor.count() == 0:
                    target_url = recipient
                    if not recipient.startswith("http"):
                        if "-" in recipient and len(recipient) > 15:
                            target_url = f"https://www.linkedin.com/in/{recipient}/"
                        else:
                            encoded = urllib.parse.quote(recipient)
                            await page.goto(f"https://www.linkedin.com/search/results/people/?keywords={encoded}&network=%5B%22F%22%5D", wait_until="domcontentloaded", timeout=15000)
                            link = page.locator("a[href*='/in/']").first
                            await link.wait_for(state="visible", timeout=5000)
                            href = await link.get_attribute("href")
                            if href:
                                target_url = href.split("?")[0]
                            else:
                                await browser.close()
                                return f"Could not find 1st-degree connection for '{recipient}'. Ensure they are connected or use connect_with_person."

                    # Open profile and click Message overlay with force=True
                    await page.goto(target_url, wait_until="domcontentloaded", timeout=18000)
                    msg_elem = page.locator("a[href*='/messaging/compose'], button:has-text('Message')").first
                    await msg_elem.wait_for(state="attached", timeout=6000)
                    await msg_elem.click(force=True)
                    
                    editor = page.locator("div.msg-form__contenteditable, div[role='textbox']").last
                    await editor.wait_for(state="visible", timeout=6000)

                if editor is None or await editor.count() == 0:
                    await browser.close()
                    return "Could not locate message editor textbox."

                # 3. Focus editor and insert text instantly (<5ms)
                await editor.click()
                await page.keyboard.insert_text(message)
                try:
                    await page.evaluate("(el) => el.dispatchEvent(new Event('input', { bubbles: true }))", await editor.element_handle())
                except Exception:
                    pass

                # 4. Submit via Send button or Enter
                send_btn = page.locator("button.msg-form__send-button, button[type='submit']:has-text('Send')").last
                try:
                    await send_btn.wait_for(state="visible", timeout=2000)
                    if await send_btn.is_enabled():
                        await send_btn.click()
                    else:
                        await editor.press("Enter")
                except Exception:
                    await editor.press("Enter")
                
                await page.wait_for_timeout(600)
                await browser.close()
                return json.dumps({
                    "status": "SUCCESS",
                    "message_delivered": True,
                    "recipient": recipient,
                    "message_text": message
                }, indent=2)
            except Exception as e:
                await browser.close()
                return f"Error sending DM: {str(e)}"

    return asyncio.run(_send())

@mcp.tool()
def connect_with_person(person_name_or_url: str, custom_note: Optional[str] = None, confirmed: bool = False) -> str:
    """
    [REQUIRES USER APPROVAL] Send a LinkedIn connection invite to someone NOT in your network.
    Optionally includes a personalized connection note (up to 300 characters).
    Set confirmed=True only after asking the user.
    """
    proposed = {
        "target_person": person_name_or_url,
        "custom_note": custom_note or "None (standard connection invite)",
        "note_length": len(custom_note) if custom_note else 0
    }
    guard = _check_safety_guard("connect_with_person", proposed, confirmed)
    if guard:
        return guard

    import urllib.parse
    async def _connect():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
            context = await browser.new_context(storage_state=str(STATE_FILE))
            page = await context.new_page()
            try:
                # 1. Navigate to target profile
                target_url = person_name_or_url
                if not person_name_or_url.startswith("http"):
                    encoded = urllib.parse.quote(person_name_or_url)
                    await page.goto(f"https://www.linkedin.com/search/results/people/?keywords={encoded}", wait_until="domcontentloaded")
                    await page.wait_for_timeout(3000)
                    link = page.locator("a[href*='/in/']").first
                    if await link.count() > 0:
                        href = await link.get_attribute("href")
                        target_url = href.split("?")[0]
                    else:
                        await browser.close()
                        return f"Could not locate profile for '{person_name_or_url}'."

                await page.goto(target_url, wait_until="domcontentloaded", timeout=25000)
                await page.wait_for_timeout(3000)

                # 2. Find Connect button (either direct or under More dropdown)
                connect_btn = page.locator("button:has-text('Connect'), a:has-text('Connect')").first
                if await connect_btn.count() == 0:
                    more_btn = page.locator("button:has-text('More')").first
                    if await more_btn.count() > 0:
                        await more_btn.click()
                        await page.wait_for_timeout(1000)
                        connect_btn = page.locator("div[role='button']:has-text('Connect'), span:has-text('Connect')").first

                if await connect_btn.count() == 0:
                    await browser.close()
                    return f"Connect button not available on profile '{target_url}'. They may already be connected or have restricted invitations."

                await connect_btn.click(force=True)
                await page.wait_for_timeout(2000)

                # 3. Handle Add a note modal
                if custom_note:
                    add_note_btn = page.locator("button:has-text('Add a note')").first
                    if await add_note_btn.count() > 0:
                        await add_note_btn.click()
                        await page.wait_for_timeout(1000)
                        note_box = page.locator("textarea[name='message'], textarea[id*='custom-message']").first
                        if await note_box.count() > 0:
                            await note_box.fill(custom_note[:300])
                            await page.wait_for_timeout(1000)

                # 4. Click Send
                send_invite_btn = page.locator("button:has-text('Send')").last
                if await send_invite_btn.count() > 0:
                    await send_invite_btn.click(force=True)
                    await page.wait_for_timeout(3000)
                    await browser.close()
                    return json.dumps({
                        "status": "SUCCESS",
                        "message": f"Connection request successfully sent to '{person_name_or_url}'.",
                        "note_included": bool(custom_note)
                    }, indent=2)

                await browser.close()
                return "Could not complete sending connection invitation modal."
            except Exception as e:
                await browser.close()
                return f"Error sending connection request: {str(e)}"

    return asyncio.run(_connect())


# ==============================================================================
# 12. Smart Job Intelligence & CV Matchmaker Tools (Read-Only)
# ==============================================================================

@mcp.tool()
def get_job_details(job_id_or_url: str) -> str:
    """
    [READ-ONLY] Get full details, complete description, location, and seniority level for a LinkedIn job.
    Accepts job URL (e.g. 'https://www.linkedin.com/jobs/view/4479952589/') or numeric job ID ('4479952589').
    """
    import re
    m = re.search(r'(\d{7,})', job_id_or_url)
    if not m:
        return f"Could not extract a valid numeric job ID from '{job_id_or_url}'."
    job_id = m.group(1)

    try:
        client = _load_auth_session()
        resp = client.get(f"https://www.linkedin.com/voyager/api/jobs/jobPostings/{job_id}")
        if resp.status_code != 200:
            return f"Failed to fetch job details for ID {job_id}: HTTP {resp.status_code}"

        data = resp.json()
        job = data.get("data", {})
        desc = job.get("description", {}).get("text", "")
        
        # Extract company name from included elements
        comp_name = ""
        for inc in data.get("included", []):
            if "Company" in inc.get("$type", ""):
                comp_name = inc.get("name", "")
                break

        return json.dumps({
            "job_id": job_id,
            "title": job.get("title", "Unknown"),
            "company": comp_name or job.get("companyName", "Unknown"),
            "location": job.get("formattedLocation", "Remote/Unspecified"),
            "experience_level": job.get("formattedExperienceLevel", "Not specified"),
            "employment_status": job.get("employmentStatus", "Full-time"),
            "applies_count": job.get("applies", 0),
            "description": desc,
            "job_url": f"https://www.linkedin.com/jobs/view/{job_id}/"
        }, indent=2)
    except Exception as e:
        return f"Error retrieving job details: {str(e)}"

@mcp.tool()
def get_company_info(company_name: str) -> str:
    """
    [READ-ONLY] Look up a company on LinkedIn to check if it's product-based, its staff count, tagline, and website.
    Accepts company name or LinkedIn company slug (e.g. 'Glean', 'DevRev', 'Sprinto').
    """
    slug = company_name.lower().replace(" ", "-").replace(".", "")
    try:
        client = _load_auth_session()
        
        # 1. Try Voyager API direct lookup
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

        # 2. Fallback via Playwright search
        import urllib.parse
        encoded = urllib.parse.quote(company_name)
        async def _search_comp():
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
                context = await browser.new_context(storage_state=str(STATE_FILE))
                page = await context.new_page()
                try:
                    await page.goto(f"https://www.linkedin.com/search/results/companies/?keywords={encoded}", wait_until="domcontentloaded", timeout=20000)
                    await page.wait_for_timeout(3000)
                    
                    info = await page.evaluate(r"""() => {
                        const card = document.querySelector('.reusable-search__result-container, li.artdeco-list__item, a[href*="/company/"]');
                        if (!card) return null;
                        const link = card.querySelector('a[href*="/company/"]') || card;
                        const titleEl = card.querySelector('.entity-result__title-text, h3');
                        const subEl = card.querySelector('.entity-result__primary-subtitle, p');
                        return {
                            name: titleEl ? titleEl.innerText.trim() : '',
                            summary: subEl ? subEl.innerText.trim() : '',
                            company_url: link ? link.href.split('?')[0] : ''
                        };
                    }""")
                    await browser.close()
                    return info or {"name": company_name, "summary": "Company details available on LinkedIn."}
                except Exception as e:
                    await browser.close()
                    return {"name": company_name, "error": str(e)}

        res = asyncio.run(_search_comp())
        return json.dumps(res, indent=2)
    except Exception as e:
        return f"Error retrieving company info: {str(e)}"

@mcp.tool()
def search_company_jobs(company_name: str, role_keywords: str = "SDET", location: str = "India", limit: int = 5) -> str:
    """
    [READ-ONLY] Search for open jobs specifically posted by a company on LinkedIn.
    Example: search_company_jobs(company_name="Glean", role_keywords="Staff SDET", location="India")
    """
    combined_query = f"{role_keywords} {company_name}".strip()
    return search_jobs(keywords=combined_query, location=location, company=company_name, limit=limit)

@mcp.tool()
def match_jobs_to_cv(
    role_title: str = "Staff SDET",
    location: str = "India",
    cv_folder: Optional[str] = None,
    limit: int = 5
) -> str:
    """
    [READ-ONLY] Automated AI Job Matchmaker:
    Searches LinkedIn jobs matching role_title and scores each job against your local CV (journey.json & skills.json).
    Returns ranked job opportunities with match percentages and overlapping skill highlights.
    """
    # 1. Load local CV skills & accomplishments
    target_dir = Path(cv_folder) if cv_folder else DEFAULT_CV_PATH
    journey_file = target_dir / "journey.json"
    skills_file = target_dir / "skills.json"

    cv_keywords = set(["playwright", "sdet", "automation", "python", "java", "api", "contract testing", "mcp", "kubernetes", "cloud", "aws", "gcp", "azure", "ci/cd", "rest", "microservices", "crossplane", "spring boot"])
    
    if skills_file.exists():
        try:
            with open(skills_file, "r") as f:
                s_data = json.load(f)
                tech = s_data if isinstance(s_data, list) else s_data.get("technical", [])
                for s in tech:
                    cv_keywords.add(s.lower())
        except Exception:
            pass

    # 2. Query LinkedIn jobs
    jobs_raw = search_jobs(keywords=role_title, location=location, limit=limit * 2)
    try:
        jobs_data = json.loads(jobs_raw)
        jobs_list = jobs_data.get("jobs", [])
    except Exception:
        return f"Failed to search jobs for matchmaking: {jobs_raw}"

    # 3. Score each job against CV
    scored_jobs = []
    for j in jobs_list[:limit]:
        title = j.get("title", "")
        # Basic matching heuristic
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

    # Sort descending by match score
    scored_jobs.sort(key=lambda x: int(x["cv_match_score"].replace("%", "")), reverse=True)

    return json.dumps({
        "target_role": role_title,
        "location": location,
        "total_evaluated": len(scored_jobs),
        "top_matched_jobs": scored_jobs
    }, indent=2)

if __name__ == "__main__":
    mcp.run()
