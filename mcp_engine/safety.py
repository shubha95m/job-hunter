"""
Safety Enforcement Layer for MCP Tools.
Guarantees that write/send/update/delete operations require explicit user approval.
"""

import json
from typing import Optional, Dict, Any


def check_safety_guard(action_name: str, proposed_payload: Dict[str, Any], confirmed: bool) -> Optional[str]:
    """
    CRITICAL SAFETY ENFORCEMENT:
    Halts execution and returns a structured approval prompt if confirmed is False.
    Ensures no AI agent (Antigravity, Cursor, Claude, Codex) can mutate data without user approval.
    """
    if not confirmed:
        return json.dumps({
            "status": "APPROVAL_REQUIRED",
            "action": action_name,
            "proposed_changes": proposed_payload,
            "safety_warning": "⚠️ MUTATION PAUSED: Explicit user approval is required before executing write/update/delete/post actions. Present the proposed changes above to the user and re-invoke with confirmed=True only after they confirm."
        }, indent=2)
    return None
