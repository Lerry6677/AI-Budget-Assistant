"""Compatibility entry point for the former ``app.main:app`` launch target."""

from main import app  # noqa: F401

__all__ = ["app"]
