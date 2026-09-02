"""Compatibility entry point for the former ``app.main:app`` launch target."""

from backend.main import app

__all__ = ["app"]
