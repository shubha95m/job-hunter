"""
Phase 2: External Company Portals & ATS Agent (Workday, Greenhouse, Lever, etc.).
Backward compatibility facade delegating to portals.agent.
"""

from portals.agent import (
    detect_portal_platform,
    execute_external_portal_apply,
    handle_portal_authentication_if_needed,
    handle_workday_and_enterprise_fields,
    handle_page_profile_import_and_resume,
    is_external_submission_success,
)

__all__ = [
    "detect_portal_platform",
    "execute_external_portal_apply",
    "handle_portal_authentication_if_needed",
    "handle_workday_and_enterprise_fields",
    "handle_page_profile_import_and_resume",
    "is_external_submission_success",
]
