"""
Session and authentication storage manager.
Safely manages cookie files for LinkedIn, Naukri, and other platforms without exposing credentials.
"""

import os
import json
from pathlib import Path
from typing import Dict, Any, Optional

BASE_DIR = Path(__file__).resolve().parent.parent

PLATFORM_AUTH_PATHS = {
    "linkedin": Path(os.getenv("LINKEDIN_AUTH_STATE", str(BASE_DIR / ".auth/state.json"))),
    "naukri": Path(os.getenv("NAUKRI_AUTH_STATE", str(BASE_DIR / ".auth/naukri_state.json"))),
}


def get_state_file(platform: str = "linkedin") -> Path:
    """Return the state file path for the requested platform."""
    return PLATFORM_AUTH_PATHS.get(platform, BASE_DIR / f".auth/{platform}_state.json")


def has_valid_session(platform: str = "linkedin") -> bool:
    """Check if the session state file exists and has non-empty cookies."""
    path = get_state_file(platform)
    if not path.exists():
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return bool(data.get("cookies"))
    except Exception:
        return False


def load_cookies(platform: str = "linkedin") -> Dict[str, str]:
    """Load cookies as a key-value dictionary from the storage state file."""
    path = get_state_file(platform)
    if not path.exists():
        raise FileNotFoundError(f"Auth state file not found at {path}. Please run auth.py first.")
    
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    cookies = {}
    for c in data.get("cookies", []):
        domain = c.get("domain", "")
        if platform == "linkedin" and "linkedin" in domain:
            cookies[c["name"]] = c["value"]
        elif platform == "naukri" and "naukri" in domain:
            cookies[c["name"]] = c["value"]
        elif platform not in ("linkedin", "naukri"):
            cookies[c["name"]] = c["value"]
            
    return cookies


def get_jsessionid(cookies: Dict[str, str]) -> str:
    """Extract and sanitize JSESSIONID token for CSRF protection on LinkedIn."""
    return cookies.get("JSESSIONID", "").strip('"')


async def save_session_state(context, state_file: Optional[Path] = None, platform: str = "linkedin"):
    """Persist the authenticated browser context storage state."""
    target_path = Path(state_file) if state_file else get_state_file(platform)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    await context.storage_state(path=str(target_path))


save_state = save_session_state

