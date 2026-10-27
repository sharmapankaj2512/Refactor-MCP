"""The refactoring workflow's state machine, independent of any language or file system."""

from __future__ import annotations

from enum import StrEnum


class FileKind(StrEnum):
    TEST = "test"
    PRODUCTION = "production"
    APPROVED = "approved"
    OTHER = "other"


class Outcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
