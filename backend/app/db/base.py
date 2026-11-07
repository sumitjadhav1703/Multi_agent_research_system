"""Declarative base for application tables.

LangGraph checkpoint tables are created by AsyncPostgresSaver.setup(), not here.
"""
from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
