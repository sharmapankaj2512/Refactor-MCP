"""Orchestrates the refactoring workflow per project: gates writes, runs tests, advances phases."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path, PurePath
from typing import Protocol

from refactor_mcp.languages.base import LanguageAdapter, SuiteRun
from refactor_mcp.phases import (
    PHASE_GUIDANCE,
    RULE_GUIDANCE,
    FileKind,
    Outcome,
    Phase,
    Rule,
    after_approval_write,
    after_coverage_check,
    after_refactor_write,
    may_write,
    next_rule,
)
from refactor_mcp.reports import SuiteCounts
from refactor_mcp.scope import Scope, expand, listing, uncovered_in_scope
from refactor_mcp.workspace import (
    Snapshot,
    replace_once,
    resolve_inside,
    restore,
    write_text,
)

OUTPUT_TAIL_CHARS = 6_000

BASELINE_IS_FROZEN = (
    "Approved output is the behavioural baseline a refactoring is measured "
    "against, so it cannot be rewritten while refactoring. If the baseline is "
    "genuinely wrong, that is a behaviour change: finish this refactoring and "
    "fix it in a TDD cycle."
)


class RefactorError(ValueError):
    """Raised when a request would break the refactoring workflow or is otherwise invalid."""


class History(Protocol):
    def head_commit(self, root: Path) -> str: ...

    def is_ancestor(self, root: Path, commit: str) -> bool: ...

    def changed_lines(self, root: Path, base: str) -> dict[str, frozenset[int]]: ...


@dataclass(frozen=True)
class Report:
    phase: Phase
    message: str
    output: str = ""
    rule: Rule | None = None

    def render(self) -> str:
        heading = f"Phase: {self.phase}"
        if self.rule:
            heading += f"\nRule: {self.rule}"
        text = f"{heading}\n{self.message}"
        if self.output:
            text += f"\n\n{self.output[-OUTPUT_TAIL_CHARS:]}"
        return text


@dataclass
class _Session:
    adapter: LanguageAdapter
    scope: Scope
    phase: Phase = Phase.COVERAGE_CHECK
    rule: Rule | None = None
    tests: int = 0
    step: Phase | None = None


class RefactorService:
    def __init__(
        self,
        adapters: Mapping[str, LanguageAdapter],
        *,
        pending_changes: Callable[[Path], list[str]],
        history: History | None = None,
        exempt: Sequence[str] = (),
    ) -> None:
        self._adapters = adapters
        self._pending_changes = pending_changes
        self._history = history
        self.exempt = tuple(exempt)
        self._sessions: dict[Path, _Session] = {}

    def status(self, location: str) -> Report:
        session = self._sessions.get(_root(location))
        if session is None:
            return Report(Phase.SCOPE_REQUIRED, PHASE_GUIDANCE[Phase.SCOPE_REQUIRED])
        return Report(session.phase, self._guidance(session), rule=session.rule)

    def declare_scope(
        self, location: str, paths: Sequence[str], language: str
    ) -> Report:
        root = _root(location)
        adapter = self._adapter(language)
        files = expand(root, paths, adapter)
        base = self._history.head_commit(root) if self._history else ""
        scope = Scope(paths=files, base=base)
        session = self._sessions[root] = _Session(adapter, scope)
        return Report(
            session.phase,
            f"Scope declared: {scope.render()}. {PHASE_GUIDANCE[session.phase]}",
        )

    def check_coverage(self, location: str) -> Report:
        root = _root(location)
        session = self._started(root)
        scope = session.scope
        run = session.adapter.run_coverage(root)
        if run.counts:
            session.tests = run.counts.tests
        session.step = None
        if run.outcome is not Outcome.PASSED:
            session.phase = Phase.APPROVAL_TESTS
            return Report(
                session.phase,
                f"Coverage run {run.outcome}. The whole suite must pass before a "
                "scope can be pinned: an approval test records what the code does "
                "today, which a failing suite can't establish. "
                f"{self._guidance(session)}",
                run.output,
            )
        gaps = uncovered_in_scope(scope, run.uncovered)
        unmeasured = scope.unmeasured(run.measured)
        session.phase = after_coverage_check(
            scope.is_covered(run.uncovered, run.measured)
        )
        session.rule = Rule.INTENTION if session.phase is Phase.REFACTORING else None
        message = "Coverage run passed."
        if unmeasured:
            message += (
                f" No test exercises {', '.join(sorted(unmeasured))} at all: "
                "absent from the coverage report means unmeasured, not covered."
            )
        elif gaps:
            message += (
                f" Lines in the scope are not covered: {listing(gaps)}. "
                "Refactoring them would be unguarded, so pin them first."
            )
        else:
            message += (
                f" Every line and branch in {scope.render()} is covered, so "
                "refactoring is unlocked."
            )
        return Report(
            session.phase,
            f"{message} {self._guidance(session)}",
            run.output,
            rule=session.rule,
        )

    def next_rule(self, location: str) -> Report:
        root = _root(location)
        session = self._refactoring(root)
        run = session.adapter.run_tests(root)
        if run.outcome is not Outcome.PASSED:
            raise RefactorError(
                f"The tests must pass before moving on: they {run.outcome}. Undo "
                "or fix your last change, then call next_rule again. You are in "
                f"the refactoring phase, rule {session.rule}."
            )
        following = next_rule(session.rule)
        if following is None:
            raise RefactorError(
                f"Rule {session.rule} is the last rule of simple design. "
                "Next: call complete_refactoring to finish this scope."
            )
        session.rule = following
        return Report(
            session.phase,
            f"Tests passed. Moving to rule {following}. {RULE_GUIDANCE[following]}",
            run.output,
            rule=following,
        )

    def complete_refactoring(self, location: str) -> Report:
        root = _root(location)
        session = self._refactoring(root)
        scope = session.scope
        run = session.adapter.run_coverage(root)
        if run.outcome is not Outcome.PASSED:
            raise RefactorError(
                f"The tests must pass to finish a refactoring: they {run.outcome}. "
                "Undo or fix your last change, then call complete_refactoring "
                "again. You are in the refactoring phase."
            )
        if not scope.is_covered(run.uncovered, run.measured):
            raise RefactorError(
                f"The scope is no longer covered: "
                f"{_gap_summary(scope, run.uncovered, run.measured)}. A refactoring "
                "must leave behaviour pinned, so delete code no test requires, "
                "then call complete_refactoring again. You are in the refactoring "
                "phase."
            )
        if commented := self._commented_changes(session, root):
            raise RefactorError(
                f"Lines changed in this refactoring hold comments: "
                f"{listing(commented)}. Remove them, letting names say what the "
                "comments did, then call complete_refactoring again. You are in "
                "the refactoring phase."
            )
        self._sessions.pop(root, None)
        return Report(
            Phase.SCOPE_REQUIRED,
            f"Refactoring complete: {scope.render()} is covered, the suite "
            "passes, and no changed line holds a comment. "
            f"{PHASE_GUIDANCE[Phase.SCOPE_REQUIRED]}",
            run.output,
        )

    def run_tests(
        self, location: str, path: str | None = None, test_name: str | None = None
    ) -> Report:
        root = _root(location)
        session = self._started(root)
        relative = None
        if path is not None:
            target = resolve_inside(root, path)
            if not target.exists():
                raise RefactorError(
                    f"Path {path!r} does not exist. Pass an existing test file or "
                    "folder relative to location, or omit path to run every test."
                )
            relative = target.relative_to(root).as_posix()
        for value in (relative, test_name):
            if value and value.startswith("-"):
                raise RefactorError(
                    f"Test selection {value!r} must not start with '-'. Pass a test "
                    "file, folder, or name without the leading '-'."
                )
        run = session.adapter.run_tests(root, relative, test_name)
        return Report(
            session.phase,
            f"Tests {run.outcome} (not a coverage run; phase unchanged).",
            run.output,
            rule=session.rule,
        )

    def write_file(self, location: str, path: str, content: str) -> Report:
        return self._apply(location, path, lambda target: write_text(target, content))

    def edit_file(
        self, location: str, path: str, old_string: str, new_string: str
    ) -> Report:
        return self._apply(
            location, path, lambda target: replace_once(target, old_string, new_string)
        )

    def _apply(
        self, location: str, path: str, change: Callable[[Path], Snapshot]
    ) -> Report:
        root = _root(location)
        session = self._started(root)
        target = resolve_inside(root, path)
        relative = target.relative_to(root)
        exempt = any(fnmatch(relative.as_posix(), pattern) for pattern in self.exempt)
        kind = session.adapter.classify(relative)
        changes = self._pending_changes(root)
        if not changes:
            session.step = session.phase
        elif session.step is None:
            if not exempt and not may_write(session.phase, kind):
                raise self._locked(session, kind, session.phase)
            raise _uncommitted(root, changes, session.phase)
        phase = session.step

        if exempt:
            change(target)
            return Report(
                session.phase,
                f"Wrote {path} (exempt from the refactoring workflow; tests not run).",
                rule=session.rule,
            )

        if not may_write(phase, kind):
            if changes and may_write(session.phase, kind):
                raise _uncommitted(root, changes, session.phase)
            raise self._locked(session, kind, phase)

        snapshot = change(target)
        if kind is FileKind.OTHER:
            return Report(
                session.phase,
                f"Wrote {path} (not code; tests not run).",
                rule=session.rule,
            )
        return self._after_write(session, root, phase, kind, path, snapshot)

    def _after_write(
        self,
        session: _Session,
        root: Path,
        phase: Phase,
        kind: FileKind,
        path: str,
        snapshot: Snapshot,
    ) -> Report:
        run = session.adapter.run_tests(root)
        counts = run.counts or SuiteCounts(tests=session.tests, failures=0)
        added = counts.tests - session.tests
        if phase is Phase.APPROVAL_TESTS:
            transition = self._pin(session, root, run, added=added, kind=kind)
        else:
            transition = after_refactor_write(run.outcome, kind, added=added)
        session.phase = transition.phase
        if transition.phase is Phase.REFACTORING and session.rule is None:
            session.rule = Rule.INTENTION
        if not transition.revert:
            session.tests = counts.tests
        message = f"Tests {run.outcome}."
        if transition.reason:
            message += f" {transition.reason}"
        if transition.revert:
            restore(snapshot)
            message += f" {path} was reverted."
        return Report(
            session.phase,
            f"{message} {self._guidance(session)}",
            run.output,
            rule=session.rule,
        )

    def _pin(self, session, root: Path, run: SuiteRun, *, added: int, kind: FileKind):
        """Whether the approval test now covers the scope, measured with coverage."""
        scope = session.scope
        covered = False
        summary = ""
        if run.outcome is Outcome.PASSED:
            coverage = session.adapter.run_coverage(root)
            covered = scope.is_covered(coverage.uncovered, coverage.measured)
            if not covered:
                summary = _gap_summary(scope, coverage.uncovered, coverage.measured)
        transition = after_approval_write(
            run.outcome, scope_covered=covered, added=added, kind=kind
        )
        if summary:
            return type(transition)(
                transition.phase,
                transition.revert,
                f"{transition.reason} Still uncovered: {summary}.",
            )
        return transition

    def _commented_changes(
        self, session: _Session, root: Path
    ) -> dict[str, frozenset[int]]:
        scope = session.scope
        if not self._history or not self._history.is_ancestor(root, scope.base):
            return {}
        commented = {}
        for path, lines in self._history.changed_lines(root, scope.base).items():
            if session.adapter.classify(PurePath(path)) is FileKind.OTHER:
                continue
            source = (root / path).read_text(encoding="utf-8", errors="replace")
            if found := lines & session.adapter.comment_lines(source):
                commented[path] = found
        return commented

    def _adapter(self, language: str) -> LanguageAdapter:
        adapter = self._adapters.get(language)
        if adapter is None:
            raise RefactorError(
                f"Unsupported language {language!r}. "
                f"Retry with language set to one of: {', '.join(self._adapters)}."
            )
        return adapter

    def _started(self, root: Path) -> _Session:
        session = self._sessions.get(root)
        if session is None:
            raise RefactorError(
                "No refactoring started for this location (you are in the "
                "scope_required phase). Next: call declare_scope with the "
                "production files you intend to refactor, then retry."
            )
        return session

    def _refactoring(self, root: Path) -> _Session:
        session = self._started(root)
        if session.phase is not Phase.REFACTORING:
            raise RefactorError(
                f"That works only while refactoring; you are in the "
                f"{session.phase} phase. {PHASE_GUIDANCE[session.phase]}"
            )
        return session

    def _guidance(self, session: _Session) -> str:
        guidance = PHASE_GUIDANCE[session.phase]
        if session.phase is Phase.REFACTORING and session.rule:
            guidance += f" {RULE_GUIDANCE[session.rule]}"
        return guidance

    def _locked(self, session: _Session, kind: FileKind, phase: Phase) -> RefactorError:
        if kind is FileKind.APPROVED and phase is Phase.REFACTORING:
            return RefactorError(f"{BASELINE_IS_FROZEN} {self._guidance(session)}")
        return RefactorError(
            f"Writing {kind} files is not allowed in the {phase} phase. "
            f"{self._guidance(session)}"
        )


def _gap_summary(
    scope: Scope, uncovered: Mapping[str, frozenset[int]], measured: frozenset[str]
) -> str:
    """What is missing in the scope: whole files no test touched, plus line gaps."""
    parts = []
    if unmeasured := scope.unmeasured(measured):
        parts.append(f"{', '.join(sorted(unmeasured))} (no test exercises it)")
    if gaps := uncovered_in_scope(scope, uncovered):
        parts.append(listing(gaps))
    return "; ".join(parts)


def _uncommitted(root: Path, changes: list[str], phase: Phase) -> RefactorError:
    return RefactorError(
        f"Uncommitted changes in {root}: "
        f"{', '.join(line.strip() for line in changes)}. "
        "Commit them first (git add, then commit: '. t' for an approval test, "
        "'. r' for a refactoring), then retry this edit. You are in the "
        f"{phase} phase."
    )


def _root(location: str) -> Path:
    root = Path(location).resolve()
    if not root.is_dir():
        raise RefactorError(
            f"Location does not exist or is not a directory: {location}. "
            "Pass the absolute path of the project root."
        )
    return root
