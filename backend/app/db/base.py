"""Declarative base for all ORM models (tables arrive in later phases)."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
