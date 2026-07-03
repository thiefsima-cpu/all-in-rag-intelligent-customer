"""Strict configuration for the live dependency integration gate."""

from .models import DEFAULT_POLICY_PATH, IntegrationGateSettings, load_integration_policy

__all__ = [
    "DEFAULT_POLICY_PATH",
    "IntegrationGateSettings",
    "load_integration_policy",
]
