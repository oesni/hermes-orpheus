"""Deprecated compatibility import; use orpheus.systemone.SystemOneClient."""
from .systemone import SystemOneClient

JevClient = SystemOneClient

# Preserve the old module's named integration helpers as well.
from .deployment import DEFAULT_JEV_ENDPOINT, validate_jev_endpoint
from .resolver import SelectionError
