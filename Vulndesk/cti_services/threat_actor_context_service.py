"""Backward-compatible alias for the harmonized CTI-S05 Threat Context Service."""
from __future__ import annotations

from .threat_context_service import ThreatContextService


class ThreatActorContextService(ThreatContextService):
    """Deprecated compatibility name.

    The previous component was presented as an autonomous threat-actor service.
    Under the harmonized architecture this is CTI-S05 Threat Context, a service
    with context-synthesis authority only.
    """

    SERVICE_KEY = "threat_context_service"
