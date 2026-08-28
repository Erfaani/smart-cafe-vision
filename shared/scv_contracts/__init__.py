"""Shared contracts between the Smart Café Vision backend and AI worker."""
from __future__ import annotations

from scv_contracts.events import (
    CONTRACT_VERSION,
    ContractError,
    Event,
    EventType,
    utcnow,
)

__all__ = ("CONTRACT_VERSION", "ContractError", "Event", "EventType", "utcnow")
