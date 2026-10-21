"""
Platform Registry & Factory.
Provides dynamic resolution and dispatch across LinkedIn, Naukri, and future platforms.
"""

from typing import Dict, Any, Optional
from platforms.base import BasePlatform


_REGISTRY: Dict[str, Any] = {}


def register_platform(name: str, platform_cls_or_instance: Any):
    """Register a new recruiter/job platform."""
    _REGISTRY[name.lower()] = platform_cls_or_instance


def get_platform(name: str = "linkedin") -> Any:
    """Retrieve an initialized platform connector."""
    name_clean = name.lower()
    if name_clean not in _REGISTRY:
        if name_clean == "linkedin":
            from platforms.linkedin import api, dom
            _REGISTRY["linkedin"] = {"api": api, "dom": dom}
        elif name_clean == "naukri":
            from platforms.naukri.api import NaukriAPIClient
            _REGISTRY["naukri"] = NaukriAPIClient()
        else:
            raise ValueError(f"Platform '{name}' is not registered. Available: {list(_REGISTRY.keys())}")
    return _REGISTRY[name_clean]
