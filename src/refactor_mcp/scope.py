"""The set of production files a refactoring covers, and whether tests reach all of it."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Protocol

from refactor_mcp.phases import FileKind
from refactor_mcp.workspace import resolve_inside

Uncovered = Mapping[str, frozenset[int]]


class ScopeError(ValueError):
    """Raised when the requested refactoring scope is unusable."""


class Classifier(Protocol):
    def classify(self, relative_path: PurePath) -> FileKind: ...


@dataclass(frozen=True)
class Scope:
    paths: frozenset[str]
    base: str

    def is_covered(self, uncovered: Uncovered) -> bool:
        return not uncovered_in_scope(self, uncovered)

    def render(self) -> str:
        return ", ".join(sorted(self.paths))


def expand(root: Path, paths: Sequence[str], adapter: Classifier) -> frozenset[str]:
    """The production files named by `paths`, with directories expanded, inside `root`."""
    if not paths:
        raise ScopeError(
            "A refactoring scope needs at least one path. Pass the production "
            "files or folders you intend to refactor, relative to location."
        )
    found: set[str] = set()
    for path in paths:
        target = resolve_inside(root, path)
        if not target.exists():
            raise ScopeError(
                f"Path {path!r} does not exist. Pass an existing file or folder "
                "relative to location."
            )
        found |= _production_files(root, target, adapter)
    if not found:
        raise ScopeError(
            f"The scope {', '.join(paths)} holds no production code. A "
            "refactoring scope is the production files whose behaviour must be "
            "pinned; tests, docs and config don't belong in it."
        )
    return frozenset(found)


def uncovered_in_scope(scope: Scope, uncovered: Uncovered) -> dict[str, frozenset[int]]:
    """The uncovered lines that fall inside `scope`, ignoring gaps elsewhere."""
    return {
        path: lines
        for path, lines in uncovered.items()
        if path in scope.paths and lines
    }


def listing(lines_by_path: Uncovered) -> str:
    return "; ".join(
        f"{path}: {', '.join(map(str, sorted(lines)))}"
        for path, lines in sorted(lines_by_path.items())
    )


def _production_files(root: Path, target: Path, adapter: Classifier) -> set[str]:
    candidates = sorted(target.rglob("*")) if target.is_dir() else [target]
    return {
        relative.as_posix()
        for candidate in candidates
        if candidate.is_file()
        and adapter.classify(relative := candidate.relative_to(root))
        is FileKind.PRODUCTION
    }
