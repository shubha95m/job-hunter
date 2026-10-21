#!/usr/bin/env python3
"""
Enterprise-Grade Local LinkedIn MCP Server for AI IDEs (Antigravity, Cursor, Claude, Codex).
Combines ultra-fast Voyager API queries with Playwright session automation.
Safety Rule: ALL write, update, delete, post, and send actions STRICTLY require confirmed=True with user approval.
"""

from mcp_engine.server import mcp

if __name__ == "__main__":
    mcp.run()
