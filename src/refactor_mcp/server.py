"""MCP server that enforces a safe refactoring workflow when changing code."""

from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from refactor_mcp import git_gate
from refactor_mcp.languages import ADAPTERS, LanguageName
from refactor_mcp.service import RefactorService

# Comma-separated fnmatch patterns of project paths that skip the refactoring workflow.
EXEMPT_ENV_VAR = "REFACTOR_MCP_EXEMPT"

mcp = MCPServer(
    "refactoring",
    instructions=(
        "Enforces a safe refactoring workflow when changing existing code. "
        "Write every code file through this server's `write_file` or "
        "`edit_file` tools, never with other editing tools. Every reply starts "
        "with 'Phase: <phase>' and says what to do next; follow it. "
        "Refactoring means changing structure without changing behaviour, so "
        "behaviour must be pinned by tests before any code moves. The workflow: "
        "(1) call `declare_scope` with the production files you intend to "
        "refactor; it is the only tool that starts the workflow. (2) Call "
        "`check_coverage`: it runs the whole suite with branch coverage and "
        "measures the scope. A fully covered scope unlocks refactoring at once; "
        "any uncovered line sends you to approval_tests. (3) approval_tests: "
        "production code is locked. Write ONE approval test that records what "
        "the scope does today — call it as a caller does, capture what it "
        "returns or prints, approve that as the baseline. Assert current "
        "behaviour, never the behaviour you wish for; a bug stays a bug through "
        "a refactoring. Refactoring unlocks when the suite passes and every "
        "line and branch in the scope is covered. (4) refactoring: work Kent "
        "Beck's rules of simple design one at a time, calling `next_rule` to "
        "move on: rule 2 reveals intention, rule 3 removes duplication, rule 4 "
        "leaves fewest elements. `next_rule` refuses while a rule has changed "
        "nothing, so each rule must do real work or be passed over with "
        "`skip_rule` and a reason; the guidance names concrete targets it found "
        "in your scope. Rule 1, passes all the tests, is always on: "
        "any edit that breaks the tests or adds a test is reverted, and "
        "approved baselines are locked so a green test can't be faked. A lower "
        "rule never justifies breaking a higher one. Call "
        "`complete_refactoring` after the last rule; it requires the suite to "
        "pass, the scope to still be covered, and no changed line to hold a "
        "comment, so say it with names instead. Call `refactor_status` any time "
        "to see the phase, rule and scope. `run_tests` never changes the phase. "
        "Non-code files (docs, config) can be written in any phase and don't "
        "run the tests. Neither do paths matching the server's "
        "`REFACTOR_MCP_EXEMPT` patterns. Commit each step before the next: use "
        "the `racn` server's `commit` tool when it is available "
        "(risk=proven_safe, intention=test_only for an approval test, "
        "intention=refactoring for a refactoring), else git add and commit "
        "with that notation ('. t', '. r'); repeat "
        "edits within one step amend it. New behaviour is not refactoring: it "
        "belongs in a test-driven cycle."
    ),
)


def new_service() -> RefactorService:
    raw = os.environ.get(EXEMPT_ENV_VAR, "")
    return RefactorService(
        ADAPTERS,
        pending_changes=git_gate.uncommitted_changes,
        history=git_gate,
        exempt=[p.strip() for p in raw.split(",") if p.strip()],
    )


service = new_service()


@contextmanager
def _refusals_as_tool_errors() -> Iterator[None]:
    # MCPServer hides the text of any exception that isn't a ToolError.
    try:
        yield
    except ValueError as e:
        raise ToolError(str(e)) from e


@mcp.tool()
def refactor_status(location: str) -> str:
    """Show the current refactoring phase, rule and scope, and what may be written.

    Args:
        location: Path to the project root.
    """
    with _refusals_as_tool_errors():
        return service.status(location).render()


@mcp.tool()
def declare_scope(
    location: str, paths: Sequence[str], language: LanguageName = "python"
) -> str:
    """Declare which production files to refactor. The only tool that starts the workflow.

    Pass the files or folders whose structure you intend to change. Folders
    expand to the production files inside them; tests, docs and config are
    ignored, so a scope of only those is refused. Call it again to start a new
    scope, which discards the current one.

    Args:
        location: Path to the project root.
        paths: Files or folders to refactor, relative to `location`.
        language: The project's language, which decides how tests are run.
    """
    with _refusals_as_tool_errors():
        return service.declare_scope(location, paths, language).render()


@mcp.tool()
def check_coverage(location: str) -> str:
    """Run the whole suite with branch coverage and measure the declared scope.

    A fully covered scope unlocks refactoring. Any uncovered line or untaken
    branch inside the scope moves you to approval_tests to pin the current
    behaviour first, and the reply lists exactly which lines are missing. Call
    it again after writing an approval test, or whenever the repository changed
    outside this server.

    Args:
        location: Path to the project root.
    """
    with _refusals_as_tool_errors():
        return service.check_coverage(location).render()


@mcp.tool()
def next_rule(location: str) -> str:
    """Move to the next of Kent Beck's rules of simple design while refactoring.

    The rules run in priority order: intention, then duplication, then fewest
    elements. Refuses while the tests fail, because rule 1 (passes all the
    tests) outranks every other rule.

    Args:
        location: Path to the project root.
    """
    with _refusals_as_tool_errors():
        return service.next_rule(location).render()


@mcp.tool()
def skip_rule(location: str, reason: str) -> str:
    """Move past a rule of simple design the code already satisfies, on the record.

    Use it only when the scope genuinely needs no change for the current rule;
    `next_rule` refuses while a rule has changed nothing, because a rule nobody
    applied is a rule nobody applied. The reason is recorded and shown in every
    later reply and in the completion summary, so say why the code already
    satisfies the rule.

    Args:
        location: Path to the project root.
        reason: Why the scope already satisfies the current rule.
    """
    with _refusals_as_tool_errors():
        return service.skip_rule(location, reason).render()


@mcp.tool()
def complete_refactoring(location: str) -> str:
    """Finish the current scope: verify the suite, the coverage and the comments.

    Requires the whole suite to pass, every line and branch in the scope to
    still be covered, and no line changed during this refactoring to hold a
    comment. Returns to scope_required, ready for the next scope.

    Args:
        location: Path to the project root.
    """
    with _refusals_as_tool_errors():
        return service.complete_refactoring(location).render()


@mcp.tool()
def run_tests(
    location: str, path: str | None = None, test_name: str | None = None
) -> str:
    """Run tests without coverage: faster, for iterating. Never changes the phase.

    Runs the whole suite by default. Narrow it with `path` (a test file or
    folder) and/or `test_name` (matched against test names: pytest `-k`,
    vitest `-t`). Only `check_coverage` and the test runs that
    `write_file`/`edit_file` trigger advance the workflow, so a passing result
    here unlocks nothing.

    Args:
        location: Path to the project root.
        path: Test file or folder, relative to `location` (or absolute, inside it).
        test_name: Name, or part of a name, of the test(s) to run.
    """
    with _refusals_as_tool_errors():
        return service.run_tests(location, path, test_name).render()


@mcp.tool()
def write_file(location: str, path: str, content: str) -> str:
    """Create or overwrite a file, if the current phase allows it, then run the tests.

    Test files may be written in approval_tests and refactoring; production
    files only in refactoring, once behaviour is pinned. Approved baselines may
    be written in approval_tests and are locked while refactoring. The test
    results decide the next phase, shown on the reply's first line.

    Args:
        location: Path to the project root.
        path: File path, relative to `location` (or absolute, inside it).
        content: The complete new file content.
    """
    with _refusals_as_tool_errors():
        return service.write_file(location, path, content).render()


@mcp.tool()
def edit_file(location: str, path: str, old_string: str, new_string: str) -> str:
    """Replace exactly one occurrence of `old_string` in a file, if the phase allows it.

    Same phase rules and test run as `write_file`. Prefer it for refactoring:
    small, reviewable changes are what keep the tests green.

    Args:
        location: Path to the project root.
        path: File path, relative to `location` (or absolute, inside it).
        old_string: Exact text to replace; must occur exactly once in the file.
        new_string: Replacement text.
    """
    with _refusals_as_tool_errors():
        return service.edit_file(location, path, old_string, new_string).render()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
