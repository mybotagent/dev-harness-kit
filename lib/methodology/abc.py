#!/usr/bin/env python3
"""abc.py — Methodology abstract base class (MUST-48)."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Dict, List


class Methodology(ABC):
    name: str
    description: str
    default_for_projects: List[str]

    @abstractmethod
    def pre_check(self, step: Dict) -> Dict: ...

    @abstractmethod
    def verification_command(self, step: Dict) -> List[str]: ...

    @abstractmethod
    def cycle_steps(self) -> List[str]: ...

    @abstractmethod
    def report_status(self, step: Dict) -> Dict: ...
