import asyncio
import subprocess
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from refactor_mcp import server
from refactor_mcp.server import (
    check_coverage,
    complete_refactoring,
    declare_scope,
    edit_file,
    mcp,
    next_rule,
    refactor_status,
    run_tests,
    write_file,
)

LEGACY = """def total(items):
    if not items:
        return 0
    return sum(price for _, price in items)
"""

APPROVAL_TEST = """from invoice import total


def test_total_pins_current_behaviour():
    assert total([("a", 2), ("b", 3)]) == 5
    assert total([]) == 0
"""


@pytest.fixture(autouse=True)
def fresh_service(monkeypatch):
    monkeypatch.setattr(server, "service", server.new_service())


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _commit_all(repo: Path) -> None:
    _git(repo, "add", "-A")
    result = subprocess.run(
        ["git", "commit", "-m", "step"], cwd=repo, capture_output=True, text=True
    )
    if result.returncode:
        raise AssertionError(f"commit failed: {result.stdout}{result.stderr}")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "invoice.py").write_text(LEGACY)
    _commit_all(tmp_path)
    return tmp_path


def test_status_before_a_scope_requires_one(repo: Path):
    assert refactor_status(str(repo)).startswith("Phase: scope_required")


def test_production_code_is_locked_until_behaviour_is_pinned(repo: Path):
    """The acceptance criterion for the whole server."""
    location = str(repo)

    with pytest.raises(ToolError, match="No refactoring started"):
        write_file(location, "invoice.py", "rewritten")

    assert declare_scope(location, ["invoice.py"]).startswith("Phase: coverage_check")
    assert check_coverage(location).startswith("Phase: approval_tests")

    with pytest.raises(ToolError, match="not allowed in the approval_tests phase"):
        write_file(location, "invoice.py", "rewritten")
    assert (repo / "invoice.py").read_text() == LEGACY


def test_a_scope_no_test_touches_is_not_treated_as_covered(repo: Path):
    """With no tests at all, coverage reports nothing: unknown, not safe."""
    location = str(repo)
    declare_scope(location, ["invoice.py"])

    report = check_coverage(location)

    assert report.startswith("Phase: approval_tests")
    assert "No test exercises invoice.py at all" in report


def test_an_unrelated_passing_test_does_not_make_the_scope_look_covered(repo: Path):
    """A scope file absent from the report has no gaps, which mimics full coverage."""
    location = str(repo)
    (repo / "test_unrelated.py").write_text("def test_sanity():\n    assert True\n")
    _commit_all(repo)
    declare_scope(location, ["invoice.py"])

    report = check_coverage(location)

    assert report.startswith("Phase: approval_tests")
    assert "No test exercises invoice.py at all" in report

    with pytest.raises(ToolError, match="not allowed in the approval_tests phase"):
        write_file(location, "invoice.py", "rewritten")
    assert (repo / "invoice.py").read_text() == LEGACY


def test_the_uncovered_lines_of_a_partly_tested_scope_are_named(repo: Path):
    location = str(repo)
    (repo / "test_other.py").write_text(
        "from invoice import total\n\n\ndef test_empty():\n    assert total([]) == 0\n"
    )
    _commit_all(repo)
    declare_scope(location, ["invoice.py"])

    report = check_coverage(location)

    assert report.startswith("Phase: approval_tests")
    assert "invoice.py: 2, 4" in report


def test_a_full_refactoring_workflow(repo: Path):
    location = str(repo)
    declare_scope(location, ["invoice.py"])
    check_coverage(location)

    pinned = write_file(location, "test_invoice.py", APPROVAL_TEST)
    assert pinned.startswith("Phase: refactoring")
    assert "Rule: intention" in pinned
    _commit_all(repo)

    renamed = edit_file(
        location,
        "invoice.py",
        "price for _, price in items",
        "cost for _, cost in items",
    )
    assert renamed.startswith("Phase: refactoring")
    _commit_all(repo)

    assert "Rule: duplication" in next_rule(location)
    assert "Rule: fewest_elements" in next_rule(location)

    with pytest.raises(ToolError, match="last rule"):
        next_rule(location)

    assert complete_refactoring(location).startswith("Phase: scope_required")


def test_a_refactoring_that_breaks_behaviour_is_reverted(repo: Path):
    location = str(repo)
    declare_scope(location, ["invoice.py"])
    check_coverage(location)
    write_file(location, "test_invoice.py", APPROVAL_TEST)
    _commit_all(repo)

    report = edit_file(location, "invoice.py", "return sum", "return 1 + sum")

    assert "was reverted" in report
    assert (repo / "invoice.py").read_text() == LEGACY


def test_a_refactoring_cannot_add_a_test(repo: Path):
    location = str(repo)
    declare_scope(location, ["invoice.py"])
    check_coverage(location)
    write_file(location, "test_invoice.py", APPROVAL_TEST)
    _commit_all(repo)

    report = write_file(location, "test_extra.py", "def test_new():\n    assert True\n")

    assert "must not add tests" in report
    assert not (repo / "test_extra.py").exists()


def test_an_already_covered_scope_skips_the_approval_test(repo: Path):
    location = str(repo)
    (repo / "test_invoice.py").write_text(APPROVAL_TEST)
    _commit_all(repo)
    declare_scope(location, ["invoice.py"])

    assert check_coverage(location).startswith("Phase: refactoring")


def test_a_scope_of_only_tests_is_refused(repo: Path):
    (repo / "test_invoice.py").write_text(APPROVAL_TEST)
    _commit_all(repo)

    with pytest.raises(ToolError, match="no production code"):
        declare_scope(str(repo), ["test_invoice.py"])


def test_a_path_outside_the_project_is_refused(repo: Path):
    with pytest.raises(ToolError, match="outside the project root"):
        declare_scope(str(repo), ["../escape.py"])


def test_completing_is_refused_while_a_changed_line_holds_a_comment(repo: Path):
    location = str(repo)
    declare_scope(location, ["invoice.py"])
    check_coverage(location)
    write_file(location, "test_invoice.py", APPROVAL_TEST)
    _commit_all(repo)
    edit_file(location, "invoice.py", "    return 0", "    return 0  # empty invoice")
    _commit_all(repo)

    with pytest.raises(ToolError, match="hold comments"):
        complete_refactoring(location)


def test_a_tool_call_through_the_protocol_reports_the_phase(repo: Path):
    result = asyncio.run(mcp.call_tool("refactor_status", {"location": str(repo)}))
    assert result.content[0].text.startswith("Phase: scope_required")


def test_server_instructions_explain_the_workflow():
    instructions = mcp.instructions
    for word in (
        "declare_scope",
        "check_coverage",
        "next_rule",
        "complete_refactoring",
        "write_file",
        "edit_file",
        "approval test",
        "behaviour",
    ):
        assert word in instructions


def test_run_tests_reports_without_changing_the_phase(repo: Path):
    location = str(repo)
    declare_scope(location, ["invoice.py"])
    check_coverage(location)

    report = run_tests(location)

    assert report.startswith("Phase: approval_tests")
    assert "phase unchanged" in report


def test_run_tests_narrows_to_a_single_test(repo: Path):
    location = str(repo)
    (repo / "test_invoice.py").write_text(APPROVAL_TEST)
    _commit_all(repo)
    declare_scope(location, ["invoice.py"])
    check_coverage(location)

    report = run_tests(location, "test_invoice.py", "pins_current_behaviour")

    assert "1 passed" in report
