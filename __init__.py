"""Hermes directory-plugin entry point; imports stay in its loader namespace."""
# Pytest may collect a checkout named with a hyphen as bare ``__init__``.
# Hermes always loads directory plugins as packages with __package__ set.
if __package__:
    from .orpheus.plugin import register
    __all__ = ['register']
else:
    __all__ = []
