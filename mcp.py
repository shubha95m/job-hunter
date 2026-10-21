#!/usr/bin/env python3
"""
Universal Multi-Platform Recruiter MCP Server (LinkedIn, Naukri, and ATS Portals).
Provides cross-platform recruiter discovery, profile audits, candidate messaging, and job matching.
Compatible with all AI IDEs: Antigravity, Cursor, Claude Desktop, Codex, and Windsurf.
"""

import sys
import os

# Prevent this local script from shadowing the official 'mcp' SDK package
_cwd = os.path.abspath(os.path.dirname(__file__))
_saved_sys_path = sys.path[:]
sys.path = [p for p in sys.path if os.path.abspath(p) != _cwd and p != ""]
try:
    import mcp as _official_mcp
finally:
    sys.path = _saved_sys_path

from mcp_engine.server import mcp

if __name__ == "__main__":
    mcp.run()
