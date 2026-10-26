"""
Abstract Base Platform Interface.
Defines the standard contract for any job/recruiter platform (LinkedIn, Naukri, Indeed, etc.).
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional


class BasePlatform(ABC):
    """Unified contract implemented by all job and recruiter platforms."""

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Return the unique platform identifier (e.g., 'linkedin', 'naukri')."""
        pass

    @abstractmethod
    def get_intro(self) -> Dict[str, Any]:
        """Fetch candidate intro details (name, headline, vanity URL)."""
        pass

    @abstractmethod
    def get_profile(self) -> Dict[str, Any]:
        """Fetch full candidate profile including about, experience, education, skills."""
        pass

    @abstractmethod
    def search_jobs(self, keywords: List[str], location: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search jobs matching keywords and location."""
        pass

    @abstractmethod
    async def search_recruiters(self, company: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search talent acquisition specialists and recruiters for a company."""
        pass

    @abstractmethod
    async def send_dm(self, recipient: str, message: str, confirmed: bool = False) -> str:
        """Send a direct message to a recruiter or connection."""
        pass
