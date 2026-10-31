"""The refactoring workflow's state machine, independent of any language or file system."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Phase(StrEnum):
    SCOPE_REQUIRED = "scope_required"
    COVERAGE_CHECK = "coverage_check"
    APPROVAL_TESTS = "approval_tests"
    REFACTORING = "refactoring"


class Rule(StrEnum):
    """Kent Beck's four rules of simple design, as the sub-states of refactoring.

    Rule 1, passes all the tests, is the always-on invariant: every write that
    breaks the suite is reverted, in every rule.
    """

    INTENTION = "intention"
    DUPLICATION = "duplication"
    FEWEST_ELEMENTS = "fewest_elements"


class FileKind(StrEnum):
    TEST = "test"
    PRODUCTION = "production"
    APPROVED = "approved"
    OTHER = "other"


class Outcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


PHASE_GUIDANCE: dict[Phase, str] = {
    Phase.SCOPE_REQUIRED: (
        "You are in the scope_required phase. Every code file is locked: tests, "
        "production code, and approved baselines. Retrying write_file or "
        "edit_file on them won't help. "
        "Next: call declare_scope with the production files you intend to "
        "refactor, which starts the workflow."
    ),
    Phase.COVERAGE_CHECK: (
        "You are in the coverage_check phase. Every code file is locked. "
        "Retrying write_file or edit_file on them won't help. "
        "Next: call check_coverage. It runs the whole suite with branch "
        "coverage and measures the scope. A fully covered scope unlocks "
        "refactoring; any uncovered line sends you to approval_tests to pin "
        "the current behaviour first. If the test runner can't run (see the "
        "output, e.g. pytest-cov or vitest not installed), you can't fix it "
        "with these tools: stop and ask the user to fix it, then call "
        "check_coverage again."
    ),
    Phase.APPROVAL_TESTS: (
        "You are in the approval_tests phase. Production code is locked; test "
        "files and approved baselines are writable. "
        "Next: write ONE approval test that pins the scope's current behaviour, "
        "with write_file or edit_file on a test file. Call the code the way a "
        "caller does, capture what it returns or prints, and approve that as "
        "the baseline; assert what the code does today, not what it should do. "
        "Refactoring unlocks once the suite passes and every line and branch in "
        "the scope is covered."
    ),
    Phase.REFACTORING: (
        "You are in the refactoring phase. Test and production code are "
        "writable; approved baselines are locked, and any edit that breaks the "
        "tests or adds a test is reverted. "
        "Next: make one small structural change, then another, committing each. "
        "Work the rules of simple design in order, calling next_rule to move on "
        "and complete_refactoring when the last rule is done."
    ),
}

RULE_GUIDANCE: dict[Rule, str] = {
    Rule.INTENTION: (
        "Rule 2 of simple design: reveals intention. "
        "Extracting methods is not enough: a wall of small methods that all "
        "poke at the same object is still procedural code with better labels. "
        "Hunt, in roughly this order of payoff: "
        "an anaemic model — a class that holds data while its rules live "
        "elsewhere; this is usually the cause the other smells are symptoms "
        "of, so fix it first; "
        "feature envy — a method that only ever touches its parameter belongs "
        "on that parameter, so move the behaviour to the data; "
        "primitive obsession — a string or number compared against several "
        "constants is a missing type, so introduce it and let it answer for "
        "itself instead of branching on its value; "
        "data clumps — the same arguments travelling together want to be one "
        "object; "
        "long methods and deep nesting — extract the steps and name them; "
        "magic values — give them names; "
        "unclear or abbreviated names; "
        "and comments that exist because the code doesn't say it. "
        "Only rule 1 (passes all the tests) outranks this: a change that "
        "breaks a test is reverted. Naming a concept often exposes the "
        "duplication it was hiding, which is rule 3's work. "
        "Next: edit for intention, then call next_rule for duplication."
    ),
    Rule.DUPLICATION: (
        "Rule 3 of simple design: no duplication. "
        "Hunt: repeated statement sequences, even when the detail inside "
        "differs — identical scaffolding around different bodies still "
        "duplicates a decision; shotgun surgery — one field written from many "
        "places should own its own changes; duplicated knowledge, where the "
        "same rule is expressed twice in different words; and data clumps. "
        "Remove each repetition once you can name what the copies share. "
        "Rule 1 (passes all the tests) and rule 2 (reveals intention) both "
        "outrank this one: extracting a badly named helper to kill duplication "
        "trades a higher rule for a lower one, so name it well or leave the "
        "duplication. Removing duplication creates an abstraction that needs a "
        "name, which sends you back to rule 2 — the two loop until both are "
        "clean at once. "
        "Next: edit for duplication, then call next_rule for fewest_elements."
    ),
    Rule.FEWEST_ELEMENTS: (
        "Rule 4 of simple design: fewest elements. "
        "Hunt: dead code, speculative generality, large classes, and needless "
        "indirection. Delete what no test requires and collapse abstractions "
        "that earn nothing. Rule 1 (passes all the tests), rule 2 (reveals "
        "intention) and rule 3 (no duplication) all outrank this one: inlining "
        "a well-named method to save an element loses intention, and rule 2 "
        "still wins. This rule applies only once rules 2 and 3 have settled, "
        "because deleting elements while duplication remains hides it instead "
        "of removing it. "
        "Next: edit for fewest elements, then call complete_refactoring."
    ),
}

_WRITABLE: dict[Phase, frozenset[FileKind]] = {
    Phase.SCOPE_REQUIRED: frozenset({FileKind.OTHER}),
    Phase.COVERAGE_CHECK: frozenset({FileKind.OTHER}),
    Phase.APPROVAL_TESTS: frozenset({FileKind.OTHER, FileKind.TEST, FileKind.APPROVED}),
    Phase.REFACTORING: frozenset({FileKind.OTHER, FileKind.TEST, FileKind.PRODUCTION}),
}

_NEXT_RULE: dict[Rule, Rule | None] = {
    Rule.INTENTION: Rule.DUPLICATION,
    Rule.DUPLICATION: Rule.FEWEST_ELEMENTS,
    Rule.FEWEST_ELEMENTS: None,
}


@dataclass(frozen=True)
class Transition:
    phase: Phase
    revert: bool = False
    reason: str = ""


def may_write(phase: Phase, kind: FileKind) -> bool:
    return kind in _WRITABLE[phase]


def next_rule(rule: Rule) -> Rule | None:
    return _NEXT_RULE[rule]


def after_coverage_check(scope_fully_covered: bool) -> Phase:
    return Phase.REFACTORING if scope_fully_covered else Phase.APPROVAL_TESTS


def after_approval_write(
    outcome: Outcome,
    *,
    scope_covered: bool,
    added: int,
    kind: FileKind = FileKind.TEST,
) -> Transition:
    """The phase that follows writing an approval test and running the tests."""
    _check_code_file(kind)
    _check_writable(Phase.APPROVAL_TESTS, kind)
    if outcome is Outcome.ERROR:
        return Transition(
            Phase.APPROVAL_TESTS,
            reason=(
                "The tests could not be collected or run, so nothing is pinned "
                "yet. Read the output and fix the test file."
            ),
        )
    if outcome is Outcome.FAILED:
        return Transition(
            Phase.APPROVAL_TESTS,
            reason=(
                "An approval test must pass before it can pin behaviour: it "
                "records what the code does today. Change the test or the "
                "approved baseline to match the current behaviour, not the "
                "behaviour you want."
            ),
        )
    if not scope_covered:
        return Transition(
            Phase.APPROVAL_TESTS,
            reason=(
                "The suite passes, but lines in the scope are still not "
                "covered, so refactoring them would be unguarded. Extend the "
                "approval test to exercise them."
            ),
        )
    return Transition(Phase.REFACTORING)


def after_refactor_write(outcome: Outcome, kind: FileKind, *, added: int) -> Transition:
    """The phase that follows writing a code file while refactoring."""
    _check_code_file(kind)
    if kind is FileKind.APPROVED:
        return Transition(
            Phase.REFACTORING,
            revert=True,
            reason=(
                "Approved output is the behavioural baseline a refactoring is "
                "measured against, so it cannot be rewritten here. If the "
                "baseline is genuinely wrong, that is a behaviour change: "
                "finish this refactoring and fix it in a TDD cycle."
            ),
        )
    _check_writable(Phase.REFACTORING, kind)
    if added > 0:
        return Transition(
            Phase.REFACTORING,
            revert=True,
            reason=(
                f"Refactoring must not add tests ({added} added); a test "
                "describes new behaviour, and new behaviour belongs in a TDD "
                "cycle. Finish refactoring first."
            ),
        )
    if outcome is not Outcome.PASSED:
        return Transition(
            Phase.REFACTORING,
            revert=True,
            reason=(
                "A refactoring must keep the tests passing, so this edit was "
                "undone. Make a smaller change: one rename, one extraction, "
                "one move."
            ),
        )
    return Transition(Phase.REFACTORING)


def _check_code_file(kind: FileKind) -> None:
    if kind is FileKind.OTHER:
        raise ValueError("Transitions apply to only code files")


def _check_writable(phase: Phase, kind: FileKind) -> None:
    if not may_write(phase, kind):
        raise ValueError(f"Writing {kind} files is not allowed in the {phase} phase")
