"""
LinkedIn Playwright DOM Actions Module.
Uses the self-recycling BrowserContextPool for fast, leak-free UI operations
(recruiter discovery, 1st-degree DMs, connections, posts).
"""

import os
import json
import asyncio
import urllib.parse
from typing import Dict, Any, List, Optional
from runtime.browser_pool import browser_pool
from runtime.dom_utils import wait_for_spinners_and_loaders

SELF_VANITY_FILTER = os.getenv("LINKEDIN_VANITY_FILTER", "")


async def search_recruiters(company: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Search active recruiters and talent acquisition leaders for a specific company."""
    query = f"recruiter at {company}"
    encoded = urllib.parse.quote(query)
    url = f"https://www.linkedin.com/search/results/people/?keywords={encoded}"

    async with browser_pool.page(platform="linkedin", headless=True) as page:
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(3000)
        
        cards = await page.evaluate(f"""([compName, maxLimit, selfVanity]) => {{
            const lis = Array.from(document.querySelectorAll("main li, .reusable-search__result-container"));
            const data = [];
            const comp = compName.toLowerCase();
            for (const li of lis) {{
                const text = (li.innerText || "");
                const textLower = text.toLowerCase();
                if (!textLower.includes(comp)) continue;
                if (!textLower.includes("recruiter") && !textLower.includes("talent") && !textLower.includes("hiring") && !textLower.includes("acquisition") && !textLower.includes("staffing")) continue;
                
                const allLinks = Array.from(li.querySelectorAll('a[href*="/in/"]'));
                for (const a of allLinks) {{
                    const titleText = (a.innerText || "").trim();
                    const href = (a.href || "").split("?")[0];
                    if (!titleText || titleText.includes("mutual") || titleText.includes("connection") || (selfVanity && href.includes(selfVanity))) continue;
                    
                    const name = titleText.split('\\n')[0].trim();
                    if (name && name.length > 2 && !data.some(d => d.profile_url === href)) {{
                        const lines = text.split('\\n').map(x => x.trim()).filter(Boolean);
                        let headline = "Recruiter at " + compName;
                        for (let i = 0; i < lines.length; i++) {{
                            if (lines[i].toLowerCase() === name.toLowerCase() && i + 1 < lines.length) {{
                                headline = lines[i+1].includes('•') && i + 2 < lines.length ? lines[i+2] : lines[i+1];
                                break;
                            }}
                        }}
                        data.push({{
                            name: name,
                            headline: headline,
                            profile_url: href,
                            company: compName
                        }});
                        break;
                    }}
                }}
                if (data.length >= maxLimit) break;
            }}
            return data;
        }}""", [company, limit, SELF_VANITY_FILTER])
        return cards


async def search_people_at_company(company_name: str, role_keyword: Optional[str] = None, limit: int = 5) -> List[Dict[str, Any]]:
    """Search for employees working at a specific company matching role_keyword."""
    query = f"{company_name} {role_keyword}".strip() if role_keyword else company_name
    encoded = urllib.parse.quote(query)
    search_url = f"https://www.linkedin.com/search/results/people/?keywords={encoded}"

    async with browser_pool.page(platform="linkedin", headless=True) as page:
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
        return people


async def find_person(query: str, in_connections_only: bool = False, limit: int = 5) -> List[Dict[str, Any]]:
    """Find any person on LinkedIn across 1st-degree and public connections."""
    encoded = urllib.parse.quote(query)
    url_1st = f"https://www.linkedin.com/search/results/people/?keywords={encoded}&network=%5B%22F%22%5D"

    async with browser_pool.page(platform="linkedin", headless=True) as page:
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
        
        if not results and not in_connections_only:
            url_pub = f"https://www.linkedin.com/search/results/people/?keywords={encoded}"
            await page.goto(url_pub, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(3000)
            results = await page.evaluate(r"""() => {
                const list = [];
                const anchors = Array.from(document.querySelectorAll('a[href*="/in/"]'));
                const seen = new Set();
                for (const a of anchors) {
                    const href = a.href.split('?')[0];
                    if (seen.has(href)) continue;
                    seen.add(href);
                    list.push({
                        name: a.innerText.trim().split('\n')[0],
                        connection_degree: '2nd/3rd+',
                        headline: '',
                        profile_url: href,
                        can_direct_message: false
                    });
                }
                return list;
            }""")
        return results[:limit]


async def send_dm(recipient: str, message: str) -> Dict[str, Any]:
    """Execute sending a direct message to a connection or profile URL."""
    async with browser_pool.page(platform="linkedin", headless=True) as page:
        if "/in/" in recipient:
            clean_url = recipient.split("?")[0]
            await page.goto(clean_url, wait_until="domcontentloaded", timeout=25000)
            await page.wait_for_timeout(3000)
            
            compose_btn = page.locator("a[href*='/messaging/compose']").first
            if await compose_btn.count() > 0:
                compose_href = await compose_btn.get_attribute("href")
                if compose_href:
                    if not compose_href.startswith("http"):
                        compose_href = "https://www.linkedin.com" + compose_href
                    await page.goto(compose_href, wait_until="domcontentloaded", timeout=20000)
                    await page.wait_for_timeout(2500)
            else:
                msg_btn = page.locator("button:has-text('Message'), button:has-text('Compose message')").first
                if await msg_btn.count() == 0:
                    raise RuntimeError(f"No direct Message button available for '{clean_url}'. They may not be a 1st-degree connection.")
                await msg_btn.click(force=True)
                await page.wait_for_timeout(2500)
        else:
            await page.goto("https://www.linkedin.com/messaging/", wait_until="domcontentloaded", timeout=25000)
            await page.wait_for_timeout(3500)
            search_input = page.locator("input[placeholder*='Search messages'], input[role='combobox']").first
            if await search_input.count() > 0:
                await search_input.click()
                await search_input.fill(recipient)
                await page.wait_for_timeout(1500)
                await search_input.press("Enter")
                await page.wait_for_timeout(2500)
                first_thread = page.locator(".msg-conversation-listitem, [data-view-name='message-thread-item']").first
                if await first_thread.count() > 0:
                    await first_thread.click()
                    await page.wait_for_timeout(2000)

        editor = page.locator("div.msg-form__contenteditable, div[role='textbox'][contenteditable='true']").last
        try:
            await editor.wait_for(state="visible", timeout=10000)
        except Exception:
            raise RuntimeError("Message composer editor could not be located or did not become visible in time.")
            
        await editor.click()
        await page.wait_for_timeout(500)
        await page.keyboard.insert_text(message)
        await page.wait_for_timeout(1000)
        send_btn = page.locator("button.msg-form__send-button, button[type='submit']:has-text('Send')").last
        await send_btn.click(force=True)
        await page.wait_for_timeout(3000)
        return {
            "status": "SUCCESS",
            "message": f"Direct message successfully dispatched to '{recipient}'."
        }


async def connect_with_person(person_name_or_url: str, custom_note: Optional[str] = None) -> Dict[str, Any]:
    """Send a connection request with an optional note."""
    async with browser_pool.page(platform="linkedin", headless=True) as page:
        target_url = person_name_or_url
        if "/in/" not in target_url:
            encoded = urllib.parse.quote(person_name_or_url)
            await page.goto(f"https://www.linkedin.com/search/results/people/?keywords={encoded}", wait_until="domcontentloaded", timeout=25000)
            await page.wait_for_timeout(3000)
            link = page.locator("a[href*='/in/']").first
            if await link.count() > 0:
                href = await link.get_attribute("href")
                target_url = (href or "").split("?")[0]
            else:
                raise RuntimeError(f"Could not locate profile for '{person_name_or_url}'.")

        await page.goto(target_url, wait_until="domcontentloaded", timeout=25000)
        await page.wait_for_timeout(3000)

        # Check if already pending or connected
        if await page.locator("button:has-text('Pending'), [role='button']:has-text('Pending')").count() > 0:
            return {
                "status": "ALREADY_PENDING",
                "message": f"A connection request to '{person_name_or_url}' has already been sent and is currently pending.",
                "profile_url": target_url
            }

        connect_btn = page.locator("button:has-text('Connect'), a:has-text('Connect')").first
        if await connect_btn.count() == 0:
            more_btn = page.locator("button:has-text('More')").first
            if await more_btn.count() > 0:
                await more_btn.click()
                await page.wait_for_timeout(1000)
                connect_btn = page.locator("div[role='button']:has-text('Connect'), span:has-text('Connect')").first

        if await connect_btn.count() == 0:
            msg_btn = page.locator("button:has-text('Message')").first
            if await msg_btn.count() > 0:
                return {
                    "status": "ALREADY_CONNECTED",
                    "message": f"You appear to already be connected with '{person_name_or_url}' (direct Message button is available).",
                    "profile_url": target_url
                }
            raise RuntimeError(f"Connect button not available on profile '{target_url}'.")

        await connect_btn.click(force=True)
        await page.wait_for_timeout(2000)

        if custom_note:
            add_note_btn = page.locator("button:has-text('Add a note')").first
            if await add_note_btn.count() > 0:
                await add_note_btn.click()
                await page.wait_for_timeout(1000)
                note_box = page.locator("textarea[name='message'], textarea[id*='custom-message']").first
                if await note_box.count() > 0:
                    await note_box.fill(custom_note[:300])
                    await page.wait_for_timeout(1000)

        send_invite_btn = page.locator("button:has-text('Send without a note'), button:has-text('Send')").last
        if await send_invite_btn.count() > 0:
            await send_invite_btn.click(force=True)
            await page.wait_for_timeout(3000)
            return {
                "status": "SUCCESS",
                "message": f"Connection request successfully sent to '{person_name_or_url}'.",
                "note_included": bool(custom_note)
            }
        raise RuntimeError("Could not complete connection modal.")


async def withdraw_sent_invitation(person_name_or_url: str) -> Dict[str, Any]:
    """Withdraw/cancel a pending connection invitation sent to a person."""
    query = person_name_or_url.strip()
    vanity = query.split("/in/")[1].strip("/").split("?")[0] if "/in/" in query else ""

    async with browser_pool.page(platform="linkedin", headless=True) as page:
        await page.goto("https://www.linkedin.com/mynetwork/invitation-manager/sent/", wait_until="domcontentloaded", timeout=25000)
        await page.wait_for_timeout(3500)

        withdraw_link = None
        links = await page.locator("a[aria-label*='Withdraw invitation sent to']").all()
        for l in links:
            aria = (await l.get_attribute("aria-label") or "").lower()
            if query.lower() in aria or (vanity and vanity.lower() in aria):
                withdraw_link = l
                break

        if not withdraw_link and vanity:
            parent = page.locator(f"div[role='listitem']:has(a[href*='{vanity}']), li:has(a[href*='{vanity}'])").first
            if await parent.count() > 0:
                withdraw_link = parent.locator("a[aria-label*='Withdraw'], button:has-text('Withdraw')").first

        if not withdraw_link:
            raise RuntimeError(f"Could not find a pending sent connection request for '{person_name_or_url}'. Check get_sent_invitations to verify active pending requests.")

        await withdraw_link.click(force=True)
        await page.wait_for_timeout(2000)

        confirm_btn = page.locator("button:has-text('Withdraw')").last
        if await confirm_btn.count() == 0:
            confirm_btn = page.locator("[role='dialog'] button:has-text('Withdraw'), .artdeco-modal button:has-text('Withdraw')").first

        if await confirm_btn.count() == 0:
            raise RuntimeError("Withdraw confirmation button did not appear in modal.")

        await confirm_btn.click(force=True)
        await page.wait_for_timeout(2500)

        return {
            "status": "SUCCESS",
            "message": f"Successfully withdrew pending connection request sent to '{person_name_or_url}'."
        }


async def get_received_invitations(limit: int = 20) -> List[Dict[str, Any]]:
    """Retrieve all pending incoming connection requests sent by others."""
    async with browser_pool.page(platform="linkedin", headless=True) as page:
        await page.goto("https://www.linkedin.com/mynetwork/invitation-manager/", wait_until="domcontentloaded", timeout=25000)
        await page.wait_for_timeout(3500)

        invitations = await page.evaluate(r"""() => {
            const list = [];
            const items = Array.from(document.querySelectorAll('div[role="listitem"], .invitation-card, .mn-invitation-list li'));
            for (const item of items) {
                const text = item.innerText || '';
                if (!text.includes('Accept') && !text.includes('Ignore') && !text.includes('Dismiss')) continue;

                const link = item.querySelector('a[href*="/in/"]');
                const titleEl = item.querySelector('a[href*="/in/"] span, .invitation-card__title, h2, h3, strong');
                const name = titleEl ? titleEl.innerText.trim() : (link ? link.innerText.trim() : 'Unknown Member');

                const lines = text.split('\n').map(s => s.trim()).filter(Boolean);
                let headline = '';
                for (const l of lines) {
                    if (l !== name && !l.includes('Accept') && !l.includes('Ignore') && !l.includes('Dismiss') && !l.includes('mutual') && l.length > 5) {
                        headline = l;
                        break;
                    }
                }

                list.push({
                    name: name.split('\n')[0].trim(),
                    headline: headline,
                    profile_url: link ? link.href.split('?')[0] : ''
                });
            }
            return list;
        }""")
        return invitations[:limit]


async def respond_to_invitation(person_name_or_url: str, action: str) -> Dict[str, Any]:
    """Accept or decline an incoming connection invitation."""
    action_norm = action.strip().lower()
    if action_norm not in ("accept", "approve", "decline", "reject", "ignore", "dismiss"):
        raise ValueError("action must be 'accept' or 'decline'/'ignore'.")

    is_accept = action_norm in ("accept", "approve")

    async with browser_pool.page(platform="linkedin", headless=True) as page:
        await page.goto("https://www.linkedin.com/mynetwork/invitation-manager/", wait_until="domcontentloaded", timeout=25000)
        await page.wait_for_timeout(3500)

        query = person_name_or_url.strip()
        vanity = query.split("/in/")[1].strip("/").split("?")[0] if "/in/" in query else ""

        target_btn = None
        cards = await page.locator("div[role='listitem'], .invitation-card, li").all()
        for c in cards:
            c_text = (await c.inner_text()).lower()
            if query.lower() in c_text or (vanity and vanity.lower() in c_text):
                btn = c.locator("button:has-text('Accept')" if is_accept else "button:has-text('Ignore'), button:has-text('Dismiss')").first
                if await btn.count() > 0:
                    target_btn = btn
                    break

        if not target_btn:
            raise RuntimeError(f"Could not find an incoming connection invitation from '{person_name_or_url}'. Verify incoming invitations list.")

        await target_btn.click(force=True)
        await page.wait_for_timeout(3000)

        action_verb = "accepted" if is_accept else "declined"
        return {
            "status": "SUCCESS",
            "action": action_verb,
            "person": person_name_or_url,
            "message": f"Successfully {action_verb} connection invitation from '{person_name_or_url}'."
        }


async def check_connection_status(person_name_or_url: str) -> Dict[str, Any]:
    """
    Check relationship and connection status for a person on LinkedIn:
    - CONNECTED (1st-degree connection)
    - PENDING_SENT (Connection request sent by you, awaiting their acceptance)
    - NOT_CONNECTED (2nd or 3rd degree, connect or follow available)
    """
    query = person_name_or_url.strip()
    vanity = query.split("/in/")[1].strip("/").split("?")[0] if "/in/" in query else ""
    q_lower = query.lower()
    vanity_lower = vanity.lower()

    # 1. Fast check: Pending sent invitations via Voyager API
    try:
        from platforms.linkedin.api import get_sent_invitations, get_connections
        sent_list = get_sent_invitations(limit=100)
        for s in sent_list:
            s_name = s.get("name", "").lower()
            s_pub = s.get("public_id", "").lower()
            if (q_lower and q_lower in s_name) or (vanity_lower and vanity_lower == s_pub) or (s_pub and s_pub in q_lower):
                return {
                    "status": "PENDING_SENT",
                    "relationship": "Invitation Sent (Pending Acceptance)",
                    "person_name": s.get("name"),
                    "headline": s.get("headline"),
                    "profile_url": s.get("profile_url"),
                    "sent_time": s.get("sent_time"),
                    "message_sent": s.get("message"),
                    "details": f"You sent a connection request to {s.get('name')} on {s.get('sent_time')}. It has not been accepted yet."
                }
    except Exception:
        pass

    # 2. Fast check: 1st-degree connections via Voyager API
    try:
        conns = get_connections(limit=200)
        for c in conns:
            c_name = c.get("name", "").lower()
            c_pub = c.get("public_id", "").lower()
            if (q_lower and q_lower in c_name) or (vanity_lower and vanity_lower == c_pub) or (c_pub and c_pub in q_lower):
                return {
                    "status": "CONNECTED",
                    "connection_degree": "1st",
                    "relationship": "1st-degree Connection",
                    "person_name": c.get("name"),
                    "headline": c.get("headline"),
                    "profile_url": c.get("profile_url"),
                    "can_direct_message": True,
                    "details": f"You are 1st-degree connected with {c.get('name')}. Direct messaging is enabled."
                }
    except Exception:
        pass

    # 3. Fallback: inspect profile page via browser pool
    async with browser_pool.page(platform="linkedin", headless=True) as page:
        target_url = query
        if "/in/" not in target_url:
            encoded = urllib.parse.quote(query)
            await page.goto(f"https://www.linkedin.com/search/results/people/?keywords={encoded}", wait_until="domcontentloaded", timeout=25000)
            await page.wait_for_timeout(3000)
            link = page.locator("a[href*='/in/']").first
            if await link.count() > 0:
                href = await link.get_attribute("href")
                target_url = (href or "").split("?")[0]
            else:
                return {
                    "status": "NOT_FOUND",
                    "query": query,
                    "details": f"Could not find any LinkedIn profile matching '{query}'."
                }

        await page.goto(target_url, wait_until="domcontentloaded", timeout=25000)
        await page.wait_for_timeout(3000)

        main_text = await page.locator("main").inner_text()

        has_pending = await page.locator("button:has-text('Pending'), div[role='button']:has-text('Pending')").count() > 0
        has_connect = await page.locator("button:has-text('Connect'), a:has-text('Connect')").count() > 0
        has_message = await page.locator("button:has-text('Message')").count() > 0
        has_1st = "· 1st" in main_text or "1st degree connection" in main_text.lower()

        if has_pending:
            return {
                "status": "PENDING_SENT",
                "relationship": "Invitation Sent (Pending Acceptance)",
                "profile_url": target_url,
                "details": "Connection invitation is currently pending acceptance."
            }
        elif has_1st or (has_message and not has_connect):
            return {
                "status": "CONNECTED",
                "connection_degree": "1st",
                "relationship": "1st-degree Connection",
                "profile_url": target_url,
                "can_direct_message": True,
                "details": "You are 1st-degree connected with this person."
            }
        else:
            return {
                "status": "NOT_CONNECTED",
                "connection_degree": "2nd or 3rd+",
                "relationship": "Not Connected",
                "profile_url": target_url,
                "can_connect": True,
                "details": "You are not connected with this person. You can send a connection request."
            }



async def search_jobs(
    keywords: str,
    location: str = "India",
    company: Optional[str] = None,
    remote_only: bool = False,
    easy_apply_only: bool = False,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """Search LinkedIn jobs with filters."""
    params = [
        f"keywords={urllib.parse.quote(keywords)}",
        f"location={urllib.parse.quote(location)}"
    ]
    if easy_apply_only:
        params.append("f_AL=true")
    if remote_only:
        params.append("f_WT=2")
    search_url = f"https://www.linkedin.com/jobs/search/?{'&'.join(params)}"

    async with browser_pool.page(platform="linkedin", headless=True) as page:
        await page.goto(search_url, wait_until="domcontentloaded", timeout=25000)
        await page.wait_for_timeout(3500)
        
        jobs = await page.evaluate(r"""() => {
            const cards = document.querySelectorAll('.job-card-container, .jobs-search-results__list-item');
            const results = [];
            for (const c of cards) {
                const titleEl = c.querySelector('.job-card-list__title, a.job-card-container__link');
                const compEl = c.querySelector('.job-card-container__primary-description, .artdeco-entity-lockup__subtitle');
                const locEl = c.querySelector('.job-card-container__metadata-item');
                const linkEl = c.querySelector('a.job-card-container__link, a[href*="/jobs/view/"]');
                const easyApplyBadge = c.querySelector('.job-card-container__apply-method') || (c.innerText && c.innerText.includes('Easy Apply'));
                
                const title = titleEl ? titleEl.innerText.split('\n')[0].trim() : 'Unknown';
                const comp = compEl ? compEl.innerText.trim() : 'Unknown';
                const loc = locEl ? locEl.innerText.trim() : '';
                const href = linkEl ? linkEl.href.split('?')[0] : '';
                
                results.push({
                    title: title,
                    company: comp,
                    location: loc,
                    easy_apply: !!easyApplyBadge,
                    job_url: href
                });
            }
            return results;
        }""")
        
        if company:
            jobs = [j for j in jobs if company.lower() in j["company"].lower()]
        return jobs[:limit]
