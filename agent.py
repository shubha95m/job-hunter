"""
Phase 1: In-Modal Easy Apply Agent.
Backward compatibility facade delegating to platforms.linkedin.easy_apply.
"""

from platforms.linkedin.easy_apply import (
    MODAL_SELECTOR,
    SYSTEM_PROMPT,
    get_easy_apply_modal,
    extract_form_context,
    execute_actions,
    execute_smart_form_fill,
)

__all__ = [
    "MODAL_SELECTOR",
    "SYSTEM_PROMPT",
    "get_easy_apply_modal",
    "extract_form_context",
    "execute_actions",
    "execute_smart_form_fill",
]
