import os

from .base import BaseITSMAdapter
from .freshservice import FreshserviceAdapter

_ADAPTERS = {}


def get_adapter(provider: str = None) -> BaseITSMAdapter:
    provider = provider or os.getenv("ITSM_PROVIDER", "freshservice")
    if provider not in _ADAPTERS:
        if provider == "freshservice":
            _ADAPTERS[provider] = FreshserviceAdapter()
        else:
            raise ValueError(f"Unknown ITSM provider: {provider}")
    return _ADAPTERS[provider]