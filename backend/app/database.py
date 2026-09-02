"""Compatibility exports for the former database module."""

from backend.database import Base, SessionLocal, engine, get_db

__all__ = ["Base", "SessionLocal", "engine", "get_db"]
