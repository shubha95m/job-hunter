"""
LinkedIn Voyager REST API Client.
High-speed, pure HTTP client querying internal LinkedIn endpoints (<250ms).
Bypasses browser rendering for reads, summaries, skills, jobs, and candidate metadata.
"""

import os
import json
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
import httpx

from runtime.session_store import load_cookies, get_jsessionid, get_state_file
from runtime.rate_limiter import api_limiter

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_CV_PATH = Path(os.getenv("DEFAULT_CV_PATH", str(BASE_DIR / "cv-content")))


def get_voyager_client() -> httpx.Client:
    """Create an authenticated httpx client using cached session cookies."""
    cookies = load_cookies("linkedin")
    jsessionid = get_jsessionid(cookies)
    
    headers = {
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "csrf-token": jsessionid,
        "x-restli-protocol-version": "2.0.0",
        "accept": "application/vnd.linkedin.normalized+json+2.1"
    }
    return httpx.Client(cookies=cookies, headers=headers, timeout=20.0)


def get_profile_metadata(client: Optional[httpx.Client] = None) -> Dict[str, Any]:
    """Retrieve profile metadata including URN, publicIdentifier, name, and headline."""
    close_client = False
    if client is None:
        client = get_voyager_client()
        close_client = True
        
    try:
        resp = client.get("https://www.linkedin.com/voyager/api/me")
        if resp.status_code != 200:
            raise RuntimeError(f"LinkedIn authentication failed with status: {resp.status_code}")
        
        included = resp.json().get("included", [])
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
    finally:
        if close_client:
            client.close()


def get_linkedin_profile() -> Dict[str, Any]:
    """Fetch complete overview of the candidate's LinkedIn profile."""
    with get_voyager_client() as client:
        meta = get_profile_metadata(client)
        public_id = meta["public_id"]
        
        dash_resp = client.get(
            f"https://www.linkedin.com/voyager/api/identity/dash/profiles?q=memberIdentity&memberIdentity={public_id}"
        )
        headline = meta["headline"]
        summary = ""
        
        if dash_resp.status_code == 200:
            for inc in dash_resp.json().get("included", []):
                if "Profile" in inc.get("$type", ""):
                    headline = inc.get("headline", headline)
                    summary = inc.get("summary") or ""
                    break
                    
        return {
            "name": f"{meta['first_name']} {meta['last_name']}".strip(),
            "first_name": meta["first_name"],
            "last_name": meta["last_name"],
            "headline": headline,
            "public_id": public_id,
            "profile_url": f"https://www.linkedin.com/in/{public_id}/",
            "about": summary
        }


def get_intro() -> Dict[str, Any]:
    """Get the intro section details: full name, headline, public vanity URL, and occupation."""
    with get_voyager_client() as client:
        meta = get_profile_metadata(client)
        return {
            "full_name": f"{meta['first_name']} {meta['last_name']}".strip(),
            "headline": meta["headline"],
            "vanity_name": meta["public_id"],
            "profile_url": f"https://www.linkedin.com/in/{meta['public_id']}/"
        }


def update_intro(headline: Optional[str] = None, first_name: Optional[str] = None, last_name: Optional[str] = None) -> Dict[str, Any]:
    """Update profile intro details."""
    with get_voyager_client() as client:
        meta = get_profile_metadata(client)
        profile_urn = meta["profile_urn"]
        if not profile_urn:
            raise RuntimeError("Could not resolve profile entity URN.")
            
        payload = {}
        if headline is not None:
            payload["headline"] = headline
        if first_name is not None:
            payload["firstName"] = first_name
        if last_name is not None:
            payload["lastName"] = last_name
            
        url = f"https://www.linkedin.com/voyager/api/identity/dash/profiles/{urllib.parse.quote(profile_urn)}"
        resp = client.post(url, json=payload, headers={"x-http-method-override": "PARTIAL_UPDATE"})
        if resp.status_code not in (200, 204):
            raise RuntimeError(f"Update intro failed with HTTP {resp.status_code}: {resp.text}")
            
        return {
            "status": "SUCCESS",
            "message": "Intro updated successfully.",
            "updated_fields": payload
        }


def get_about() -> Dict[str, Any]:
    """Get the candidate's about/summary section."""
    with get_voyager_client() as client:
        meta = get_profile_metadata(client)
        dash_resp = client.get(
            f"https://www.linkedin.com/voyager/api/identity/dash/profiles?q=memberIdentity&memberIdentity={meta['public_id']}"
        )
        summary = ""
        if dash_resp.status_code == 200:
            for inc in dash_resp.json().get("included", []):
                if "Profile" in inc.get("$type", ""):
                    summary = inc.get("summary", "")
                    break
        return {"about": summary}


def update_about(about_text: str) -> Dict[str, Any]:
    """Update the candidate's about/summary section."""
    with get_voyager_client() as client:
        meta = get_profile_metadata(client)
        profile_urn = meta["profile_urn"]
        if not profile_urn:
            raise RuntimeError("Could not resolve profile entity URN.")
            
        url = f"https://www.linkedin.com/voyager/api/identity/dash/profiles/{urllib.parse.quote(profile_urn)}"
        resp = client.post(url, json={"summary": about_text}, headers={"x-http-method-override": "PARTIAL_UPDATE"})
        if resp.status_code not in (200, 204):
            raise RuntimeError(f"Update about failed with HTTP {resp.status_code}: {resp.text}")
            
        return {
            "status": "SUCCESS",
            "message": "About section updated successfully.",
            "about_length": len(about_text)
        }


def get_experience() -> List[Dict[str, Any]]:
    """List all work experiences."""
    with get_voyager_client() as client:
        meta = get_profile_metadata(client)
        urn = meta["profile_urn"]
        url = f"https://www.linkedin.com/voyager/api/identity/dash/profiles/{urllib.parse.quote(urn)}/positionGroups"
        resp = client.get(url)
        positions = []
        if resp.status_code == 200:
            for item in resp.json().get("included", []):
                if "Position" in item.get("$type", ""):
                    positions.append({
                        "entity_urn": item.get("entityUrn", ""),
                        "title": item.get("title", ""),
                        "company": item.get("companyName", ""),
                        "location": item.get("locationName", ""),
                        "description": item.get("description", "")
                    })
        return positions


def get_education() -> List[Dict[str, Any]]:
    """List educational qualifications."""
    with get_voyager_client() as client:
        meta = get_profile_metadata(client)
        url = f"https://www.linkedin.com/voyager/api/identity/dash/profiles/{urllib.parse.quote(meta['profile_urn'])}/educations"
        resp = client.get(url)
        edu_list = []
        if resp.status_code == 200:
            for item in resp.json().get("included", []):
                if "Education" in item.get("$type", ""):
                    edu_list.append({
                        "school": item.get("schoolName", ""),
                        "degree": item.get("degreeName", ""),
                        "field_of_study": item.get("fieldOfStudy", "")
                    })
        return edu_list


def get_skills() -> List[str]:
    """Retrieve all listed skills."""
    with get_voyager_client() as client:
        meta = get_profile_metadata(client)
        url = f"https://www.linkedin.com/voyager/api/identity/dash/profiles/{urllib.parse.quote(meta['profile_urn'])}/skills"
        resp = client.get(url)
        skills = []
        if resp.status_code == 200:
            for item in resp.json().get("included", []):
                if "Skill" in item.get("$type", ""):
                    name = item.get("name")
                    if name and name not in skills:
                        skills.append(name)
        return skills


def get_unread_messages() -> List[Dict[str, Any]]:
    """Retrieve unread message threads from the LinkedIn inbox."""
    with get_voyager_client() as client:
        url = "https://www.linkedin.com/voyager/api/messaging/conversations?q=unread"
        resp = client.get(url)
        messages = []
        if resp.status_code == 200:
            for item in resp.json().get("included", []):
                if "Conversation" in item.get("$type", ""):
                    messages.append({
                        "entity_urn": item.get("entityUrn", ""),
                        "unread_count": item.get("unreadCount", 0)
                    })
        return messages


def get_job_details(job_id_or_url: str) -> Dict[str, Any]:
    """Get full details, complete description, location, and seniority for a job."""
    import re
    m = re.search(r'(\d{7,})', job_id_or_url)
    if not m:
        raise ValueError(f"Could not extract a valid numeric job ID from '{job_id_or_url}'.")
    job_id = m.group(1)

    with get_voyager_client() as client:
        resp = client.get(f"https://www.linkedin.com/voyager/api/jobs/jobPostings/{job_id}")
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to fetch job details for ID {job_id}: HTTP {resp.status_code}")

        data = resp.json()
        job = data.get("data", {})
        desc = job.get("description", {}).get("text", "")
        
        comp_name = ""
        for inc in data.get("included", []):
            if "Company" in inc.get("$type", ""):
                comp_name = inc.get("name", "")
                break

        return {
            "job_id": job_id,
            "title": job.get("title", "Unknown"),
            "company": comp_name or job.get("companyName", "Unknown"),
            "location": job.get("formattedLocation", "Remote/Unspecified"),
            "experience_level": job.get("formattedExperienceLevel", "Not specified"),
            "employment_status": job.get("employmentStatus", "Full-time"),
            "applies_count": job.get("applies", 0),
            "description": desc,
            "job_url": f"https://www.linkedin.com/jobs/view/{job_id}/"
        }


def get_connections(limit: int = 50, start: int = 0, sort_by: str = "RECENTLY_ADDED") -> List[Dict[str, Any]]:
    """
    Retrieve candidate's 1st-degree connections with details (name, headline, public identifier, profile URL).
    Ultra-fast query using internal Voyager relationships API.
    """
    with get_voyager_client() as client:
        url = f"https://www.linkedin.com/voyager/api/relationships/connections?count={limit}&sortType={sort_by}&start={start}"
        resp = client.get(url)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to fetch LinkedIn connections: HTTP {resp.status_code}")
            
        data = resp.json()
        connections = []
        for inc in data.get("included", []):
            if "MiniProfile" in inc.get("$type", ""):
                first_name = inc.get("firstName", "")
                last_name = inc.get("lastName", "")
                public_id = inc.get("publicIdentifier", "")
                headline = inc.get("occupation", "")
                entity_urn = inc.get("entityUrn", "")
                dash_urn = inc.get("dashEntityUrn", "")
                
                connections.append({
                    "name": f"{first_name} {last_name}".strip(),
                    "first_name": first_name,
                    "last_name": last_name,
                    "headline": headline,
                    "public_id": public_id,
                    "profile_url": f"https://www.linkedin.com/in/{public_id}/" if public_id else "",
                    "entity_urn": entity_urn,
                    "dash_urn": dash_urn
                })
        return connections


def get_sent_invitations(limit: int = 50, start: int = 0) -> List[Dict[str, Any]]:
    """
    Retrieve all pending connection requests sent to others that have not yet been accepted.
    Extracts recipient profile details, timestamp, and optional custom invitation note.
    """
    with get_voyager_client() as client:
        url = f"https://www.linkedin.com/voyager/api/relationships/sentInvitationViewsV2?invitationType=CONNECTION&q=invitationType&count={limit}&start={start}"
        resp = client.get(url)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to fetch sent invitations: HTTP {resp.status_code}")
            
        data = resp.json()
        
        # Build mini-profile lookup map
        profiles = {}
        for inc in data.get("included", []):
            if "MiniProfile" in inc.get("$type", ""):
                urn = inc.get("entityUrn")
                first = inc.get("firstName", "")
                last = inc.get("lastName", "")
                pub_id = inc.get("publicIdentifier", "")
                profiles[urn] = {
                    "name": f"{first} {last}".strip(),
                    "first_name": first,
                    "last_name": last,
                    "headline": inc.get("occupation", ""),
                    "public_id": pub_id,
                    "profile_url": f"https://www.linkedin.com/in/{pub_id}/" if pub_id else "",
                    "entity_urn": urn,
                    "dash_urn": inc.get("dashEntityUrn", "")
                }
                
        invitations = []
        for inc in data.get("included", []):
            if inc.get("$type") == "com.linkedin.voyager.relationships.invitation.Invitation":
                to_urn = inc.get("*toMember") or inc.get("toMemberId")
                if not to_urn and isinstance(inc.get("invitee"), dict):
                    to_urn = inc.get("invitee", {}).get("*miniProfile")
                prof = profiles.get(to_urn, {})
                sent_ms = inc.get("sentTime")
                sent_formatted = ""
                if sent_ms:
                    try:
                        sent_formatted = datetime.fromtimestamp(sent_ms / 1000.0).strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        sent_formatted = str(sent_ms)
                        
                invitations.append({
                    "name": prof.get("name", "Unknown Member"),
                    "headline": prof.get("headline", ""),
                    "public_id": prof.get("public_id", ""),
                    "profile_url": prof.get("profile_url", ""),
                    "sent_time": sent_formatted,
                    "sent_time_ms": sent_ms,
                    "invitation_urn": inc.get("entityUrn", ""),
                    "mailbox_item_id": inc.get("mailboxItemId", ""),
                    "message": inc.get("message")
                })
        return invitations

