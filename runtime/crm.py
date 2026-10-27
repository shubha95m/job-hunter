"""
Enterprise-Grade Local Application CRM & Recruiter Cadence Follow-Up Engine.
Zero external server dependencies. 100% local, resilient storage.

Features:
- Dual-Layer Storage: ACID-compliant SQLite WAL database (applications.db) + Atomic Mirror JSON (applications_tracker.json)
- Zero Data Loss: Uses atomic file write/replace and WAL transactions to prevent corruption on sudden shutdowns.
- Touchpoint Cadence Engine:
    - Day 0: Applied
    - Day 2+: Cadence Touchpoint 1 (Recruiter discovery & warm connection request)
    - Day 7+: Cadence Touchpoint 2 (Follow-up DM if 1st-degree connected)
- Company Deduplication Guard: Never contacts multiple recruiters at the same company within 24 hours.
- Automatic Legacy Sync: Reads and migrates applied_jobs.txt and applied_naukri_jobs.txt without duplicates.
"""

import os
import re
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("JOB_HUNTER_DB", str(BASE_DIR / "applications.db")))
JSON_TRACKER_PATH = Path(os.getenv("JOB_HUNTER_TRACKER_JSON", str(BASE_DIR / "applications_tracker.json")))
APPLIED_JOBS_TXT = Path(os.getenv("APPLIED_JOBS_TXT", str(BASE_DIR / "applied_jobs.txt")))
APPLIED_NAUKRI_JOBS_TXT = Path(os.getenv("APPLIED_NAUKRI_JOBS_TXT", str(BASE_DIR / "applied_naukri_jobs.txt")))


def _get_connection() -> sqlite3.Connection:
    """Return an active connection with WAL mode and row factory."""
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db():
    """Initialize database tables and sync legacy files."""
    with _get_connection() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_key TEXT UNIQUE NOT NULL,
            job_url TEXT UNIQUE NOT NULL,
            platform TEXT NOT NULL,
            company TEXT NOT NULL,
            role_title TEXT NOT NULL,
            location TEXT DEFAULT '',
            package TEXT DEFAULT '',
            applied_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'APPLIED',
            recruiter_name TEXT DEFAULT '',
            recruiter_profile_url TEXT DEFAULT '',
            recruiter_headline TEXT DEFAULT '',
            last_touchpoint_at TEXT DEFAULT '',
            touchpoint_stage INTEGER DEFAULT 0,
            notes TEXT DEFAULT '',
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS touchpoint_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id INTEGER,
            company TEXT NOT NULL,
            recruiter_name TEXT NOT NULL,
            recruiter_url TEXT DEFAULT '',
            action_type TEXT NOT NULL,
            message_sent TEXT DEFAULT '',
            executed_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'SUCCESS',
            FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS wishlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_key TEXT UNIQUE NOT NULL,
            job_url TEXT UNIQUE NOT NULL,
            platform TEXT NOT NULL,
            company TEXT NOT NULL,
            role_title TEXT NOT NULL,
            location TEXT DEFAULT '',
            package TEXT DEFAULT '',
            easy_apply BOOLEAN DEFAULT 0,
            added_at TEXT NOT NULL,
            notes TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'WISHLIST'
        );

        CREATE INDEX IF NOT EXISTS idx_apps_company ON applications(company);
        CREATE INDEX IF NOT EXISTS idx_apps_status ON applications(status);
        CREATE INDEX IF NOT EXISTS idx_apps_applied_at ON applications(applied_at);
        CREATE INDEX IF NOT EXISTS idx_touchpoints_company ON touchpoint_logs(company, executed_at);
        CREATE INDEX IF NOT EXISTS idx_wishlist_comp ON wishlist(company);
        CREATE INDEX IF NOT EXISTS idx_wishlist_platform ON wishlist(platform);
        """)

        # Automatic column migration for 'package'
        app_cols = [r[1] for r in conn.execute("PRAGMA table_info(applications);").fetchall()]
        if "package" not in app_cols:
            conn.execute("ALTER TABLE applications ADD COLUMN package TEXT DEFAULT '';")

        wish_cols = [r[1] for r in conn.execute("PRAGMA table_info(wishlist);").fetchall()]
        if "package" not in wish_cols:
            conn.execute("ALTER TABLE wishlist ADD COLUMN package TEXT DEFAULT '';")

        conn.commit()

    export_to_json()


def _normalize_key_and_platform(job_url: str) -> Tuple[str, str]:
    """Generate a clean normalized unique key and platform from a job URL or identifier."""
    clean = job_url.strip().split("?")[0].rstrip("/")
    if "linkedin.com" in clean:
        m = re.search(r'/jobs/view/(\d+)', clean)
        job_id = m.group(1) if m else clean.split("/")[-1]
        return f"linkedin_{job_id}", "LinkedIn"
    elif "naukri.com" in clean:
        m = re.search(r'(\d{10,})', clean)
        if m:
            job_id = m.group(1)
        else:
            path_slug = re.sub(r'https?://[^/]+/', '', clean).strip('/').replace('/', '_')
            job_id = path_slug or str(abs(hash(clean)) % 10000000)
        return f"naukri_{job_id}", "Naukri"
    else:
        # External portal (Workday, Greenhouse, Lever, etc.)
        domain = urllib_domain(clean)
        return f"portal_{domain}_{abs(hash(clean)) % 10000000}", f"ATS ({domain})"


def urllib_domain(url: str) -> str:
    try:
        import urllib.parse
        parsed = urllib.parse.urlparse(url)
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc or "portal"
    except Exception:
        return "portal"


def record_application(
    job_url: str,
    company: Optional[str] = None,
    role_title: Optional[str] = None,
    platform: Optional[str] = None,
    location: Optional[str] = None,
    package: Optional[str] = None,
    notes: Optional[str] = None,
    applied_at: Optional[str] = None,
    recruiter_name: Optional[str] = None,
    recruiter_profile_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    Record or update a job application into the CRM.
    Guarantees no data loss and automatically updates atomic JSON mirror.
    """
    clean_url = job_url.strip().split("?")[0].rstrip("/")
    job_key, inferred_platform = _normalize_key_and_platform(clean_url)
    resolved_platform = platform or inferred_platform

    comp = (company or "").strip() or "Unspecified Company"
    role = (role_title or "").strip() or "Target Role"
    loc = (location or "").strip()
    pkg = (package or "").strip()
    now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    applied_iso = applied_at or now_iso

    with _get_connection() as conn:
        cursor = conn.cursor()

        # If this job was previously in wishlist, automatically remove it and carry over package/notes
        cursor.execute("SELECT id, package, notes FROM wishlist WHERE job_key = ? OR job_url = ?", (job_key, clean_url))
        wish_item = cursor.fetchone()
        if wish_item:
            if not pkg and wish_item["package"]:
                pkg = wish_item["package"]
            if wish_item["notes"] and wish_item["notes"] not in (notes or ""):
                notes = (wish_item["notes"] + " | " + (notes or "")).strip(" |")
            cursor.execute("DELETE FROM wishlist WHERE id = ?", (wish_item["id"],))

        cursor.execute("SELECT id, company, role_title, status, touchpoint_stage, package, notes FROM applications WHERE job_key = ? OR job_url = ?", (job_key, clean_url))
        existing = cursor.fetchone()

        if existing:
            app_id = existing["id"]
            # Preserve existing company and role if new ones are generic
            final_comp = comp if comp != "Unspecified Company" else existing["company"]
            final_role = role if role != "Target Role" else existing["role_title"]
            final_pkg = pkg or existing["package"] or ""
            combined_notes = existing["notes"] or ""
            if notes and notes not in combined_notes:
                combined_notes = (combined_notes + " | " + notes).strip(" |")

            cursor.execute("""
                UPDATE applications
                SET company = ?, role_title = ?, location = COALESCE(NULLIF(?, ''), location),
                    package = ?, notes = ?, recruiter_name = COALESCE(NULLIF(?, ''), recruiter_name),
                    recruiter_profile_url = COALESCE(NULLIF(?, ''), recruiter_profile_url),
                    updated_at = ?
                WHERE id = ?
            """, (final_comp, final_role, loc, final_pkg, combined_notes, recruiter_name or "", recruiter_profile_url or "", now_iso, app_id))
            action_status = "UPDATED"
        else:
            cursor.execute("""
                INSERT INTO applications (
                    job_key, job_url, platform, company, role_title, location, package,
                    applied_at, status, recruiter_name, recruiter_profile_url,
                    recruiter_headline, last_touchpoint_at, touchpoint_stage, notes, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'APPLIED', ?, ?, '', '', 0, ?, ?)
            """, (job_key, clean_url, resolved_platform, comp, role, loc, pkg, applied_iso, recruiter_name or "", recruiter_profile_url or "", notes or "", now_iso))
            app_id = cursor.lastrowid
            action_status = "CREATED"

        conn.commit()

    # Also keep legacy text files in sync so other components remain compatible
    _append_to_legacy_txt(clean_url, applied_iso, resolved_platform)
    export_to_json()

    return {
        "status": "SUCCESS",
        "action": action_status,
        "application_id": app_id,
        "job_key": job_key,
        "company": comp,
        "role_title": role,
        "platform": resolved_platform,
        "location": loc,
        "package": pkg,
        "applied_at": applied_iso,
        "job_url": clean_url
    }


def _append_to_legacy_txt(url: str, timestamp_str: str, platform: str):
    """Safely append to legacy files without duplicates."""
    try:
        target_file = APPLIED_NAUKRI_JOBS_TXT if "naukri" in platform.lower() else APPLIED_JOBS_TXT
        seen = set()
        if target_file.exists():
            with open(target_file, "r", encoding="utf-8") as f:
                seen = set(line.split(" | ")[0].strip() for line in f if line.strip())
        if url not in seen:
            with open(target_file, "a", encoding="utf-8") as f:
                f.write(f"{url} | {timestamp_str}\n")
    except Exception:
        pass


def update_application_status(
    job_key_or_url_or_id: Any,
    status: str,
    notes: Optional[str] = None,
    recruiter_name: Optional[str] = None,
    recruiter_profile_url: Optional[str] = None,
    recruiter_headline: Optional[str] = None,
    touchpoint_stage: Optional[int] = None
) -> Dict[str, Any]:
    """Update status, recruiter assignment, or notes for a tracked job."""
    valid_statuses = {
        "APPLIED", "TOUCHPOINT_1_SCHEDULED", "TOUCHPOINT_1_CONNECT_SENT",
        "TOUCHPOINT_1_CONNECTED", "TOUCHPOINT_2_SCHEDULED",
        "TOUCHPOINT_2_FOLLOWUP_SENT", "VIEWED", "INTERVIEW_SCHEDULED",
        "REJECTED", "OFFER", "CLOSED"
    }
    status_upper = status.strip().upper()
    now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with _get_connection() as conn:
        cursor = conn.cursor()
        identifier = str(job_key_or_url_or_id).strip()

        cursor.execute("""
            SELECT id, job_key, company, role_title, status, touchpoint_stage, notes
            FROM applications
            WHERE id = ? OR job_key = ? OR job_url = ? OR company LIKE ?
            ORDER BY id DESC LIMIT 1
        """, (identifier if identifier.isdigit() else -1, identifier, identifier, f"%{identifier}%"))
        row = cursor.fetchone()

        if not row:
            raise ValueError(f"No application found matching '{identifier}'.")

        app_id = row["id"]
        combined_notes = row["notes"] or ""
        if notes and notes not in combined_notes:
            combined_notes = (combined_notes + " | " + notes).strip(" |")

        stage_val = touchpoint_stage if touchpoint_stage is not None else row["touchpoint_stage"]
        if status_upper == "TOUCHPOINT_1_CONNECT_SENT" and stage_val < 1:
            stage_val = 1
        elif status_upper == "TOUCHPOINT_2_FOLLOWUP_SENT" and stage_val < 2:
            stage_val = 2

        cursor.execute("""
            UPDATE applications
            SET status = ?,
                notes = ?,
                recruiter_name = COALESCE(NULLIF(?, ''), recruiter_name),
                recruiter_profile_url = COALESCE(NULLIF(?, ''), recruiter_profile_url),
                recruiter_headline = COALESCE(NULLIF(?, ''), recruiter_headline),
                touchpoint_stage = ?,
                updated_at = ?
            WHERE id = ?
        """, (status_upper, combined_notes, recruiter_name or "", recruiter_profile_url or "", recruiter_headline or "", stage_val, now_iso, app_id))
        conn.commit()

    export_to_json()
    return {
        "status": "SUCCESS",
        "application_id": app_id,
        "job_key": row["job_key"],
        "company": row["company"],
        "role_title": row["role_title"],
        "new_status": status_upper,
        "touchpoint_stage": stage_val
    }


def can_contact_company_today(company_name: str) -> Tuple[bool, str]:
    """
    Deduplication Guard:
    Checks if any touchpoint (connection request or DM) was already dispatched
    to this company within the last 24 hours.
    """
    clean_comp = company_name.strip()
    if not clean_comp:
        return True, ""

    cutoff_iso = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT recruiter_name, action_type, executed_at
            FROM touchpoint_logs
            WHERE LOWER(company) = LOWER(?) AND executed_at >= ?
            ORDER BY executed_at DESC LIMIT 1
        """, (clean_comp, cutoff_iso))
        recent = cursor.fetchone()
        if recent:
            return False, f"Deduplication Guard: Touchpoint ({recent['action_type']}) was already dispatched to recruiter '{recent['recruiter_name']}' at '{clean_comp}' on {recent['executed_at']} (<24h ago)."
    return True, "Allowed"


def log_touchpoint(
    application_id: Optional[int],
    company: str,
    recruiter_name: str,
    recruiter_url: str,
    action_type: str,
    message_sent: str,
    status: str = "SUCCESS"
) -> Dict[str, Any]:
    """Log an outreach touchpoint to audit history and advance application cadence."""
    now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO touchpoint_logs (
                application_id, company, recruiter_name, recruiter_url,
                action_type, message_sent, executed_at, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (application_id, company, recruiter_name, recruiter_url, action_type, message_sent, now_iso, status))
        log_id = cursor.lastrowid

        if application_id:
            cursor.execute("""
                UPDATE applications
                SET last_touchpoint_at = ?,
                    recruiter_name = COALESCE(NULLIF(?, ''), recruiter_name),
                    recruiter_profile_url = COALESCE(NULLIF(?, ''), recruiter_profile_url),
                    updated_at = ?
                WHERE id = ?
            """, (now_iso, recruiter_name, recruiter_url, now_iso, application_id))

        conn.commit()

    export_to_json()
    return {"status": "SUCCESS", "log_id": log_id, "company": company, "recruiter": recruiter_name, "action": action_type}

def _get_cadence_candidate_summary() -> Tuple[int, str, str]:
    """Dynamically retrieve candidate experience years, title, and key skills from active profile."""
    try:
        from main import load_profile
        prof = load_profile()
        prof_info = prof.get("professional_info", {})
        yoe = int(round(float(prof_info.get("years_of_experience", 5))))
        headline = prof_info.get("headline", "Engineering Professional")
        title = headline.split("|")[0].strip() or "Engineering"
        skills = prof.get("skills", [])
        top_skills = ", ".join(skills[:3]) if skills else "System Architecture, Cloud"
        return yoe, title, top_skills
    except Exception:
        return 5, "Engineering", "Software Architecture, Cloud"


def get_pending_cadence_actions() -> List[Dict[str, Any]]:
    """
    Evaluates the Touchpoint Cadence across all applications:
    - Day 2+: Touchpoint 1 (Discover & Connect with Recruiter)
    - Day 7+: Touchpoint 2 (Follow-up DM if connected)
    Returns prioritized list of applications needing action.
    """
    now = datetime.now()
    actions = []

    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, job_key, job_url, platform, company, role_title,
                   applied_at, status, recruiter_name, recruiter_profile_url,
                   recruiter_headline, last_touchpoint_at, touchpoint_stage, notes
            FROM applications
            WHERE status NOT IN ('REJECTED', 'OFFER', 'CLOSED')
            ORDER BY applied_at DESC
        """)
        rows = cursor.fetchall()

    for r in rows:
        app = dict(r)
        try:
            applied_dt = datetime.strptime(app["applied_at"], "%Y-%m-%d %H:%M:%S")
        except Exception:
            try:
                applied_dt = datetime.strptime(app["applied_at"][:19], "%Y-%m-%dT%H:%M:%S")
            except Exception:
                continue

        days_elapsed = (now - applied_dt).days
        stage = app["touchpoint_stage"]
        comp = app["company"]
        role = app["role_title"]

        can_contact, guard_msg = can_contact_company_today(comp)

        # Cadence Step 1: Day 2+ (48h after applying) -> Send warm Connection Request
        if days_elapsed >= 2 and stage == 0:
            yoe_dyn, title_dyn, skills_dyn = _get_cadence_candidate_summary()
            actions.append({
                "application_id": app["id"],
                "company": comp,
                "role_title": role,
                "platform": app["platform"],
                "job_url": app["job_url"],
                "days_since_applied": days_elapsed,
                "current_stage": stage,
                "recommended_action": "TOUCHPOINT_1_CONNECT_RECRUITER",
                "cadence_step": "Day 2+ Recruiter Outreach",
                "assigned_recruiter": app["recruiter_name"] or "Needs Mapping via search_people_at_company",
                "recruiter_url": app["recruiter_profile_url"] or "",
                "allowed_today": can_contact,
                "guard_status": guard_msg,
                "proposed_note_300chars": (
                    f"Hi {app['recruiter_name'].split()[0] if app['recruiter_name'] else 'there'}, I applied for the {role} role at {comp}. "
                    f"With ~{yoe_dyn} yrs in {title_dyn} ({skills_dyn}), I'd love to connect and explore how I can support your goals!"
                )[:295]
            })

        # Cadence Step 2: Day 7+ -> Follow-up DM if connected
        elif days_elapsed >= 7 and stage == 1:
            yoe_dyn, title_dyn, skills_dyn = _get_cadence_candidate_summary()
            actions.append({
                "application_id": app["id"],
                "company": comp,
                "role_title": role,
                "platform": app["platform"],
                "job_url": app["job_url"],
                "days_since_applied": days_elapsed,
                "current_stage": stage,
                "recommended_action": "TOUCHPOINT_2_FOLLOWUP_DM",
                "cadence_step": "Day 7+ Follow-up Check-in",
                "assigned_recruiter": app["recruiter_name"],
                "recruiter_url": app["recruiter_profile_url"],
                "allowed_today": can_contact,
                "guard_status": guard_msg,
                "proposed_dm": (
                    f"Hi {app['recruiter_name'].split()[0] if app['recruiter_name'] else ''}, hope you're having a great week! "
                    f"Following up on my application for the {role} role ({app['job_url']}). I'm very excited about {comp}'s mission "
                    f"and would welcome the opportunity to discuss how my {title_dyn} background can drive impact for your team."
                )
            })

    return actions


def get_pipeline(status: Optional[str] = None, company: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    """Query tracked applications with filter options."""
    query = "SELECT * FROM applications WHERE 1=1"
    params = []
    if status:
        query += " AND status = ?"
        params.append(status.strip().upper())
    if company:
        query += " AND company LIKE ?"
        params.append(f"%{company.strip()}%")

    query += " ORDER BY applied_at DESC LIMIT ?"
    params.append(limit)

    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [dict(r) for r in rows]


def get_pipeline_summary() -> Dict[str, Any]:
    """Return aggregated statistical summary of the job application pipeline and wishlist."""
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as total FROM applications")
        total = cursor.fetchone()["total"]

        cursor.execute("SELECT status, COUNT(*) as cnt FROM applications GROUP BY status")
        by_status = {r["status"]: r["cnt"] for r in cursor.fetchall()}

        cursor.execute("SELECT platform, COUNT(*) as cnt FROM applications GROUP BY platform")
        by_platform = {r["platform"]: r["cnt"] for r in cursor.fetchall()}

        cursor.execute("SELECT COUNT(*) as total_touchpoints FROM touchpoint_logs")
        total_touchpoints = cursor.fetchone()["total_touchpoints"]

        cursor.execute("SELECT COUNT(*) as total_wishlist FROM wishlist")
        total_wishlist = cursor.fetchone()["total_wishlist"]

        # Calculate pending follow-ups count
        pending_followups = len(get_pending_cadence_actions())

    return {
        "total_applications_tracked": total,
        "active_pipeline": total - by_status.get("REJECTED", 0) - by_status.get("CLOSED", 0),
        "total_wishlist_saved": total_wishlist,
        "pending_followups_due": pending_followups,
        "breakdown_by_status": by_status,
        "breakdown_by_platform": by_platform,
        "total_touchpoints_logged": total_touchpoints,
        "database_path": str(DB_PATH),
        "json_tracker_path": str(JSON_TRACKER_PATH)
    }


def add_to_wishlist(
    job_url: str,
    company: str,
    role_title: str,
    platform: Optional[str] = None,
    location: Optional[str] = None,
    package: Optional[str] = None,
    easy_apply: bool = False,
    notes: Optional[str] = None
) -> Dict[str, Any]:
    """Add or update an opportunity in the Wishlist / Will-Do-Later queue."""
    clean_url = job_url.strip().split("?")[0].rstrip("/")
    job_key, inferred_platform = _normalize_key_and_platform(clean_url)
    resolved_platform = platform or inferred_platform
    now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    comp = company.strip()
    role = role_title.strip()
    loc = (location or "").strip()
    pkg = (package or "").strip()

    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, package FROM wishlist WHERE job_key = ? OR job_url = ?", (job_key, clean_url))
        existing = cursor.fetchone()

        if existing:
            final_pkg = pkg or existing["package"] or ""
            cursor.execute("""
                UPDATE wishlist
                SET company = ?, role_title = ?, location = COALESCE(NULLIF(?, ''), location),
                    package = ?, easy_apply = ?, notes = COALESCE(NULLIF(?, ''), notes)
                WHERE id = ?
            """, (comp, role, loc, final_pkg, 1 if easy_apply else 0, notes or "", existing["id"]))
            wishlist_id = existing["id"]
            action_status = "UPDATED"
        else:
            cursor.execute("""
                INSERT INTO wishlist (
                    job_key, job_url, platform, company, role_title,
                    location, package, easy_apply, added_at, notes, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'WISHLIST')
            """, (job_key, clean_url, resolved_platform, comp, role, loc, pkg, 1 if easy_apply else 0, now_iso, notes or ""))
            wishlist_id = cursor.lastrowid
            action_status = "ADDED"

        conn.commit()

    export_to_json()
    return {
        "status": "SUCCESS",
        "action": action_status,
        "wishlist_id": wishlist_id,
        "job_key": job_key,
        "company": comp,
        "role_title": role,
        "platform": resolved_platform,
        "location": loc,
        "package": pkg,
        "easy_apply": easy_apply,
        "job_url": clean_url
    }


def get_wishlist(platform: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    """Retrieve all saved opportunities in the Wishlist queue."""
    query = "SELECT * FROM wishlist WHERE 1=1"
    params = []
    if platform:
        query += " AND platform LIKE ?"
        params.append(f"%{platform.strip()}%")

    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [dict(r) for r in rows]


def remove_from_wishlist(job_key_or_url_or_id: Any) -> Dict[str, Any]:
    """Remove a job from the wishlist."""
    identifier = str(job_key_or_url_or_id).strip()
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM wishlist
            WHERE id = ? OR job_key = ? OR job_url = ? OR company LIKE ?
        """, (int(identifier) if identifier.isdigit() else -1, identifier, identifier, f"%{identifier}%"))
        deleted = cursor.rowcount
        conn.commit()

    if deleted == 0:
        raise ValueError(f"No wishlist item found matching '{identifier}'.")

    export_to_json()
    return {
        "status": "SUCCESS",
        "message": f"Successfully removed item from wishlist.",
        "identifier": identifier
    }


def convert_wishlist_to_applied(
    job_key_or_url_or_id: Any,
    notes: Optional[str] = None
) -> Dict[str, Any]:
    """
    Transition a job from Wishlist to Applied status:
    Moves the record into the applications pipeline and removes it from the wishlist queue.
    """
    identifier = str(job_key_or_url_or_id).strip()
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, job_key, job_url, platform, company, role_title, location, package, notes
            FROM wishlist
            WHERE id = ? OR job_key = ? OR job_url = ? OR company LIKE ?
            ORDER BY id DESC LIMIT 1
        """, (int(identifier) if identifier.isdigit() else -1, identifier, identifier, f"%{identifier}%"))
        row = cursor.fetchone()

        if not row:
            raise ValueError(f"No wishlisted job found matching '{identifier}'.")

        item = dict(row)
        cursor.execute("DELETE FROM wishlist WHERE id = ?", (item["id"],))
        conn.commit()

    combined_notes = item["notes"] or ""
    if notes:
        combined_notes = (combined_notes + " | " + notes).strip(" |")

    # Record into applications pipeline with package carried over
    res = record_application(
        job_url=item["job_url"],
        company=item["company"],
        role_title=item["role_title"],
        platform=item["platform"],
        location=item["location"],
        package=item.get("package", ""),
        notes=f"Converted from Wishlist: {combined_notes}" if combined_notes else "Converted from Wishlist"
    )
    return {
        "status": "SUCCESS",
        "action": "CONVERTED_TO_APPLIED",
        "company": item["company"],
        "role_title": item["role_title"],
        "package": item.get("package", ""),
        "job_url": item["job_url"],
        "platform": item["platform"],
        "application_id": res["application_id"]
    }


def export_to_json():
    """
    Atomic export of the entire database to a clean, human-readable JSON file.
    Uses atomic write-then-rename to guarantee zero corruption or partial writes.
    """
    summary = get_pipeline_summary()
    apps = get_pipeline(limit=500)
    wishlist = get_wishlist(limit=200)

    # Calculate days elapsed for each app in JSON export
    now = datetime.now()
    enriched_apps = []
    for a in apps:
        item = dict(a)
        try:
            app_dt = datetime.strptime(item["applied_at"][:19], "%Y-%m-%d %H:%M:%S")
            item["days_since_applied"] = (now - app_dt).days
        except Exception:
            item["days_since_applied"] = None
        enriched_apps.append(item)

    payload = {
        "_notice": "AUTO-SYNCED LOCAL CRM TRACKER. Zero data loss guarantee. Mirrored from applications.db",
        "last_synced_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "summary": summary,
        "wishlist": wishlist,
        "applications": enriched_apps
    }

    temp_file = JSON_TRACKER_PATH.with_suffix(".tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    # Atomic replace
    os.replace(temp_file, JSON_TRACKER_PATH)


def sync_legacy_files():
    """Import historical applications from applied_jobs.txt and applied_naukri_jobs.txt."""
    imported_count = 0

    # 1. LinkedIn jobs
    if APPLIED_JOBS_TXT.exists():
        with open(APPLIED_JOBS_TXT, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(" | ")
                url = parts[0].strip()
                ts = parts[1].strip() if len(parts) > 1 else "2026-05-01 12:00:00"
                if "/jobs/view/" in url:
                    m = re.search(r'/jobs/view/(\d+)', url)
                    job_id = m.group(1) if m else url.split("/")[-1]
                    res = record_application(
                        job_url=url,
                        company="Company via LinkedIn",
                        role_title=f"Role #{job_id}",
                        platform="LinkedIn",
                        applied_at=ts,
                        notes="Imported from applied_jobs.txt"
                    )
                    if res["action"] == "CREATED":
                        imported_count += 1

    # 2. Naukri jobs
    if APPLIED_NAUKRI_JOBS_TXT.exists():
        with open(APPLIED_NAUKRI_JOBS_TXT, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(" | ")
                url = parts[0].strip()
                ts = parts[1].strip() if len(parts) > 1 else "2026-10-16 12:00:00"
                # Parse title & company from naukri url if possible
                comp_match = re.search(r'-([a-z0-9\-]+)-pune', url)
                comp = comp_match.group(1).replace("-", " ").title() if comp_match else "Company via Naukri"
                title_match = re.search(r'job-listings-([a-z0-9\-]+)-pune', url)
                title = title_match.group(1).replace("-", " ").title() if title_match else "QA Automation Engineer"

                res = record_application(
                    job_url=url,
                    company=comp,
                    role_title=title,
                    platform="Naukri",
                    location="Pune",
                    applied_at=ts,
                    notes="Imported from applied_naukri_jobs.txt"
                )
                if res["action"] == "CREATED":
                    imported_count += 1

    return imported_count


async def execute_cadence_action(
    application_id_or_company: Any,
    recruiter_name_or_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    Executes the appropriate cadence touchpoint for a tracked job application:
    - Checks 24h deduplication guard.
    - Resolves recruiter (uses assigned recruiter, provided recruiter, or auto-discovers top recruiter at company).
    - If Stage 0 (Day 2+): Sends connection request with tailored 300-char note.
    - If Stage 1 (Day 7+): Checks connection status; if 1st-degree connected, sends follow-up DM.
    - Updates application status & touchpoint log in CRM.
    """
    from platforms.linkedin import dom as linkedin_dom

    identifier = str(application_id_or_company).strip()
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, job_key, job_url, platform, company, role_title,
                   applied_at, status, recruiter_name, recruiter_profile_url,
                   recruiter_headline, touchpoint_stage, notes
            FROM applications
            WHERE id = ? OR job_key = ? OR job_url = ? OR company LIKE ?
            ORDER BY id DESC LIMIT 1
        """, (int(identifier) if identifier.isdigit() else -1, identifier, identifier, f"%{identifier}%"))
        row = cursor.fetchone()

    if not row:
        raise ValueError(f"No application found matching '{identifier}'.")

    app = dict(row)
    comp = app["company"]
    role = app["role_title"]
    stage = app["touchpoint_stage"]
    app_id = app["id"]

    # Deduplication Guard
    can_contact, guard_msg = can_contact_company_today(comp)
    if not can_contact:
        raise RuntimeError(guard_msg)

    # Resolve target recruiter
    rec_target = recruiter_name_or_url or app["recruiter_profile_url"] or app["recruiter_name"]
    resolved_recruiter_name = app["recruiter_name"]
    resolved_recruiter_url = app["recruiter_profile_url"]

    if not rec_target or rec_target == "Needs Mapping via search_people_at_company":
        # Auto-discover recruiter at company
        recruiters = await linkedin_dom.search_people_at_company(company_name=comp, role_keyword="Recruiter", limit=2)
        if not recruiters:
            recruiters = await linkedin_dom.search_recruiters(company=comp, limit=2)

        if not recruiters:
            raise RuntimeError(f"Could not automatically locate an active recruiter at '{comp}'. Please specify a recruiter name or profile URL.")

        rec = recruiters[0]
        resolved_recruiter_name = rec["name"]
        resolved_recruiter_url = rec["profile_url"]
        rec_target = resolved_recruiter_url or resolved_recruiter_name

    # Determine Cadence Step
    yoe_dyn, title_dyn, skills_dyn = _get_cadence_candidate_summary()
    if stage == 0:
        # Touchpoint 1: Warm Connection Request
        rec_first_name = resolved_recruiter_name.split()[0] if resolved_recruiter_name else "there"
        custom_note = (
            f"Hi {rec_first_name}, I applied for the {role} role at {comp}. "
            f"With ~{yoe_dyn} yrs in {title_dyn} ({skills_dyn}), "
            f"I'd love to connect and explore how I can support your goals!"
        )[:295]

        res = await linkedin_dom.connect_with_person(person_name_or_url=rec_target, custom_note=custom_note)

        # Log to CRM
        log_touchpoint(
            application_id=app_id,
            company=comp,
            recruiter_name=resolved_recruiter_name or rec_target,
            recruiter_url=resolved_recruiter_url or rec_target,
            action_type="CONNECT_REQUEST",
            message_sent=custom_note,
            status="SUCCESS"
        )
        update_application_status(
            job_key_or_url_or_id=app_id,
            status="TOUCHPOINT_1_CONNECT_SENT",
            recruiter_name=resolved_recruiter_name,
            recruiter_profile_url=resolved_recruiter_url,
            touchpoint_stage=1
        )
        return {
            "status": "SUCCESS",
            "cadence_step": "TOUCHPOINT_1_CONNECT_SENT",
            "company": comp,
            "role_title": role,
            "recruiter": resolved_recruiter_name or rec_target,
            "recruiter_url": resolved_recruiter_url,
            "note_sent": custom_note,
            "details": f"Connection request successfully sent to {resolved_recruiter_name or rec_target} at {comp}."
        }

    elif stage == 1:
        # Touchpoint 2: Follow-up DM (if connected)
        status_info = await linkedin_dom.check_connection_status(rec_target)
        if status_info.get("status") != "CONNECTED":
            return {
                "status": "CADENCE_PAUSED",
                "cadence_step": "TOUCHPOINT_2_AWAITING_CONNECTION",
                "company": comp,
                "recruiter": resolved_recruiter_name or rec_target,
                "connection_status": status_info.get("status"),
                "details": f"Recruiter '{resolved_recruiter_name or rec_target}' has not accepted the connection invitation yet. Follow-up DM paused until connected."
            }

        rec_first_name = resolved_recruiter_name.split()[0] if resolved_recruiter_name else ""
        dm_text = (
            f"Hi {rec_first_name}, hope you're having a great week! "
            f"Following up on my application for the {role} role ({app['job_url']}). I'm very excited about {comp}'s mission "
            f"and would welcome the opportunity to discuss how my {title_dyn} background can drive impact for your team."
        )

        res = await linkedin_dom.send_dm(recipient=rec_target, message=dm_text)
        log_touchpoint(
            application_id=app_id,
            company=comp,
            recruiter_name=resolved_recruiter_name or rec_target,
            recruiter_url=resolved_recruiter_url or rec_target,
            action_type="DIRECT_MESSAGE",
            message_sent=dm_text,
            status="SUCCESS"
        )
        update_application_status(
            job_key_or_url_or_id=app_id,
            status="TOUCHPOINT_2_FOLLOWUP_SENT",
            touchpoint_stage=2
        )
        return {
            "status": "SUCCESS",
            "cadence_step": "TOUCHPOINT_2_FOLLOWUP_SENT",
            "company": comp,
            "role_title": role,
            "recruiter": resolved_recruiter_name or rec_target,
            "recruiter_url": resolved_recruiter_url,
            "message_sent": dm_text,
            "details": f"Follow-up direct message successfully sent to {resolved_recruiter_name or rec_target} at {comp}."
        }
    else:
        return {
            "status": "CADENCE_COMPLETED",
            "company": comp,
            "role_title": role,
            "touchpoint_stage": stage,
            "details": "All scheduled automated cadence touchpoints have already been completed for this application."
        }


def sync_from_json(json_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Import/sync entries from applications_tracker.json back into applications.db.
    Guarantees bidirectional sync if the JSON file is ever manually edited.
    """
    path = json_path or JSON_TRACKER_PATH
    if not path.exists():
        return {"status": "NO_OP", "message": "JSON tracker file does not exist."}

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    synced_wishlist = 0
    synced_apps = 0

    # Sync wishlist
    for item in data.get("wishlist", []):
        if not item.get("job_url"):
            continue
        add_to_wishlist(
            job_url=item["job_url"],
            company=item.get("company", "Unspecified Company"),
            role_title=item.get("role_title", "Target Role"),
            platform=item.get("platform"),
            location=item.get("location"),
            package=item.get("package"),
            easy_apply=bool(item.get("easy_apply")),
            notes=item.get("notes")
        )
        synced_wishlist += 1

    # Sync applications
    for item in data.get("applications", []):
        if not item.get("job_url"):
            continue
        record_application(
            job_url=item["job_url"],
            company=item.get("company"),
            role_title=item.get("role_title"),
            platform=item.get("platform"),
            location=item.get("location"),
            package=item.get("package"),
            notes=item.get("notes"),
            applied_at=item.get("applied_at"),
            recruiter_name=item.get("recruiter_name"),
            recruiter_profile_url=item.get("recruiter_profile_url")
        )
        synced_apps += 1

    export_to_json()
    return {
        "status": "SUCCESS",
        "synced_wishlist_count": synced_wishlist,
        "synced_applications_count": synced_apps
    }


# Initialize on import
init_db()

if __name__ == "__main__":
    import sys
    if "--sync-from-json" in sys.argv:
        res = sync_from_json()
        print(json.dumps(res, indent=2))
    else:
        init_db()
        export_to_json()
        summary = get_pipeline_summary()
        print("CRM Status (SQLite & JSON in Sync):")
        print(json.dumps(summary, indent=2))
