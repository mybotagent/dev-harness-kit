#!/usr/bin/env python3
"""methodology/__init__.py — Registry of available methodologies (MUST-48)."""
from __future__ import annotations
from .tdd import INSTANCE as TDD_INSTANCE


def get_methodology(name: str):
    registry = {"tdd": TDD_INSTANCE}
    return registry[name]


def list_methodologies():
    return ["tdd"]
