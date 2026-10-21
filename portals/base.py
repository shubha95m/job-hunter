"""
Base Portal Handler Interface.
Defines the contract for external ATS platforms (Workday, Greenhouse, Lever, Taleo, Ashby).
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from playwright.async_api import Page


class BasePortalHandler(ABC):
    """Abstract strategy for handling specific external applicant tracking systems."""

    @property
    @abstractmethod
    def ats_name(self) -> str:
        """Name of the ATS platform (e.g., 'workday', 'greenhouse', 'lever')."""
        pass

    @abstractmethod
    async def match_portal(self, page: Page) -> bool:
        """Return True if this handler matches the current portal page/URL."""
        pass

    @abstractmethod
    async def apply(self, page: Page, profile: Dict[str, Any], job_title: str) -> bool:
        """Execute autonomous form filling and submission."""
        pass
