from __future__ import annotations

from enum import Enum


class StopType(str, Enum):
    DEPOT = "depot"
    TASK = "task"
    CONTACT = "contact"


class ExecutionMode(str, Enum):
    LOCAL = "local"
    OFFLOAD = "offload"
