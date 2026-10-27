from pathlib import Path, PurePath

import pytest

from refactor_mcp.languages.base import SuiteRun
from refactor_mcp.phases import FileKind, Outcome, Phase, Rule
from refactor_mcp.reports import SuiteCounts
from refactor_mcp.service import RefactorError, RefactorService, Report


class FakeAdapter:
    """A made-up language: `test*` files are tests, `*.code` files are production."""

    name = "fake"

    def __init__(self) -> None:
        self.outcome = Outcome.PASSED
        self.counts = SuiteCounts(tests=1, failures=0)
        self.uncovered: dict[str, frozenset[int]] = {}
        self.measured = True
        self.test_runs = 0
        self.selections: list[tuple[str | None, str | None]] = []

    def classify(self, relative_path: PurePath) -> FileKind:
        if ".approved." in relative_path.name:
            return FileKind.APPROVED
        if relative_path.name.startswith("test"):
            return FileKind.TEST
        if relative_path.suffix == ".code":
            return FileKind.PRODUCTION
        return FileKind.OTHER

    def comment_lines(self, source: str) -> frozenset[int]:
        return frozenset(
            number
            for number, line in enumerate(source.splitlines(), start=1)
            if "#" in line
        )

    def run_tests(
        self, root: Path, path: str | None = None, test_name: str | None = None
    ) -> SuiteRun:
        self.test_runs += 1
        self.selections.append((path, test_name))
        return SuiteRun(self.outcome, "test output", self.counts)

    def run_coverage(self, root: Path) -> SuiteRun:
        return SuiteRun(
            self.outcome,
            "coverage output",
            self.counts,
            self.uncovered,
            measured=self.measured,
        )


class FakeTree:
    """Reports `changes` as uncommitted, recording which roots were checked."""

    def __init__(self) -> None:
        self.changes: list[str] = []
        self.checked: list[Path] = []

    def __call__(self, root: Path) -> list[str]:
        self.checked.append(root)
        return list(self.changes)


class FakeHistory:
    def __init__(self) -> None:
        self.head = "commit0"
        self.ancestor = True
        self.changed: dict[str, frozenset[int]] = {}

    def head_commit(self, root: Path) -> str:
        return self.head

    def is_ancestor(self, root: Path, commit: str) -> bool:
        return self.ancestor

    def changed_lines(self, root: Path, base: str) -> dict[str, frozenset[int]]:
        return dict(self.changed)


@pytest.fixture
def adapter() -> FakeAdapter:
    return FakeAdapter()


@pytest.fixture
def tree() -> FakeTree:
    return FakeTree()


@pytest.fixture
def history() -> FakeHistory:
    return FakeHistory()


@pytest.fixture
def service(adapter, tree, history) -> RefactorService:
    return RefactorService({"fake": adapter}, pending_changes=tree, history=history)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "invoice.code").write_text("line one\nline two\n")
    return tmp_path


def _declare(service: RefactorService, root: Path) -> Report:
    return service.declare_scope(str(root), ["invoice.code"], "fake")


def _to_refactoring(service, adapter, root: Path) -> Report:
    _declare(service, root)
    return service.check_coverage(str(root))


def test_status_before_a_scope_requires_one(service, project):
    report = service.status(str(project))
    assert report.phase is Phase.SCOPE_REQUIRED
    assert "declare_scope" in report.message


def test_writing_before_a_scope_is_refused(service, project):
    with pytest.raises(RefactorError, match="No refactoring started"):
        service.write_file(str(project), "invoice.code", "x")
    assert (project / "invoice.code").read_text() == "line one\nline two\n"


def test_location_must_be_a_directory(service, tmp_path):
    with pytest.raises(RefactorError, match="not a directory"):
        service.status(str(tmp_path / "missing"))


def test_unknown_language_is_refused(service, project):
    with pytest.raises(RefactorError, match="Unsupported language 'cobol'.*fake"):
        service.declare_scope(str(project), ["invoice.code"], "cobol")


def test_declaring_a_scope_moves_to_coverage_check(service, project):
    report = _declare(service, project)
    assert report.phase is Phase.COVERAGE_CHECK
    assert "invoice.code" in report.message


def test_a_covered_scope_unlocks_refactoring_directly(service, adapter, project):
    """Legacy code that already has tests needs no approval test."""
    report = _to_refactoring(service, adapter, project)
    assert report.phase is Phase.REFACTORING
    assert report.message.startswith("Coverage run passed.")


def test_an_uncovered_scope_routes_to_approval_tests(service, adapter, project):
    adapter.uncovered = {"invoice.code": frozenset({2})}
    report = _to_refactoring(service, adapter, project)
    assert report.phase is Phase.APPROVAL_TESTS
    assert "invoice.code: 2" in report.message


def test_coverage_gaps_outside_the_scope_do_not_block(service, adapter, project):
    adapter.uncovered = {"elsewhere.code": frozenset({7})}
    assert _to_refactoring(service, adapter, project).phase is Phase.REFACTORING


def test_a_failing_suite_blocks_the_coverage_check(service, adapter, project):
    adapter.outcome = Outcome.FAILED
    report = _to_refactoring(service, adapter, project)
    assert report.phase is Phase.APPROVAL_TESTS
    assert "must pass" in report.message


def test_production_code_is_locked_while_pinning_behaviour(service, adapter, project):
    """The central guarantee: no structural edit before the baseline exists."""
    adapter.uncovered = {"invoice.code": frozenset({2})}
    _to_refactoring(service, adapter, project)

    with pytest.raises(RefactorError, match="not allowed in the approval_tests phase"):
        service.write_file(str(project), "invoice.code", "refactored")
    assert (project / "invoice.code").read_text() == "line one\nline two\n"


def test_a_passing_approval_test_that_covers_the_scope_unlocks_refactoring(
    service, adapter, project
):
    adapter.uncovered = {"invoice.code": frozenset({2})}
    _to_refactoring(service, adapter, project)
    adapter.uncovered = {}

    report = service.write_file(str(project), "test_invoice", "pins behaviour")

    assert report.phase is Phase.REFACTORING
    assert report.rule is Rule.INTENTION


def test_an_approval_test_that_leaves_gaps_stays_in_approval_tests(
    service, adapter, project
):
    adapter.uncovered = {"invoice.code": frozenset({2})}
    _to_refactoring(service, adapter, project)

    report = service.write_file(str(project), "test_invoice", "partial")

    assert report.phase is Phase.APPROVAL_TESTS
    assert "invoice.code: 2" in report.message


def test_a_failing_approval_test_cannot_pin_behaviour(service, adapter, project):
    adapter.uncovered = {"invoice.code": frozenset({2})}
    _to_refactoring(service, adapter, project)
    adapter.outcome = Outcome.FAILED

    report = service.write_file(str(project), "test_invoice", "wrong")

    assert report.phase is Phase.APPROVAL_TESTS
    assert "must pass" in report.message


def test_an_approved_baseline_may_be_written_while_pinning(service, adapter, project):
    adapter.uncovered = {"invoice.code": frozenset({2})}
    _to_refactoring(service, adapter, project)

    report = service.write_file(str(project), "test_invoice.approved.txt", "baseline")

    assert (project / "test_invoice.approved.txt").read_text() == "baseline"
    assert report.phase is Phase.APPROVAL_TESTS


def test_refactoring_accepts_an_edit_that_keeps_the_tests_green(
    service, adapter, project
):
    _to_refactoring(service, adapter, project)

    report = service.edit_file(str(project), "invoice.code", "line one", "first line")

    assert report.phase is Phase.REFACTORING
    assert (project / "invoice.code").read_text() == "first line\nline two\n"


def test_a_refactoring_that_breaks_the_tests_is_reverted(service, adapter, project):
    _to_refactoring(service, adapter, project)
    adapter.outcome = Outcome.FAILED

    report = service.edit_file(str(project), "invoice.code", "line one", "broken")

    assert "was reverted" in report.message
    assert (project / "invoice.code").read_text() == "line one\nline two\n"


def test_a_refactoring_that_adds_a_test_is_reverted(service, adapter, project):
    _to_refactoring(service, adapter, project)
    adapter.counts = SuiteCounts(tests=2, failures=0)

    report = service.write_file(str(project), "test_extra", "new behaviour")

    assert "must not add tests" in report.message
    assert not (project / "test_extra").exists()


def test_rewriting_an_approved_baseline_while_refactoring_is_refused(
    service, adapter, project
):
    """Re-approving output is the one way to fake a green approval test."""
    (project / "invoice.approved.txt").write_text("pinned")
    _to_refactoring(service, adapter, project)

    with pytest.raises(RefactorError, match="behavioural baseline"):
        service.write_file(str(project), "invoice.approved.txt", "moved baseline")
    assert (project / "invoice.approved.txt").read_text() == "pinned"


def test_a_refused_baseline_write_never_runs_the_tests(service, adapter, project):
    (project / "invoice.approved.txt").write_text("pinned")
    _to_refactoring(service, adapter, project)
    before = adapter.test_runs

    with pytest.raises(RefactorError):
        service.write_file(str(project), "invoice.approved.txt", "moved")

    assert adapter.test_runs == before


def test_a_refused_baseline_write_says_where_a_behaviour_change_belongs(
    service, adapter, project
):
    (project / "invoice.approved.txt").write_text("pinned")
    _to_refactoring(service, adapter, project)

    with pytest.raises(RefactorError, match="TDD cycle"):
        service.write_file(str(project), "invoice.approved.txt", "moved")


def test_the_rules_advance_one_at_a_time(service, adapter, project):
    _to_refactoring(service, adapter, project)
    location = str(project)

    assert service.status(location).rule is Rule.INTENTION
    assert service.next_rule(location).rule is Rule.DUPLICATION
    assert service.next_rule(location).rule is Rule.FEWEST_ELEMENTS


def test_the_last_rule_cannot_advance_further(service, adapter, project):
    _to_refactoring(service, adapter, project)
    location = str(project)
    service.next_rule(location)
    service.next_rule(location)

    with pytest.raises(RefactorError, match="last rule"):
        service.next_rule(location)


def test_next_rule_is_refused_outside_refactoring(service, project):
    _declare(service, project)
    with pytest.raises(RefactorError, match="only while refactoring"):
        service.next_rule(str(project))


def test_next_rule_is_refused_while_the_tests_fail(service, adapter, project):
    _to_refactoring(service, adapter, project)
    adapter.outcome = Outcome.FAILED

    with pytest.raises(RefactorError, match="tests must pass"):
        service.next_rule(str(project))


def test_completing_a_refactoring_returns_to_scope_required(service, adapter, project):
    _to_refactoring(service, adapter, project)

    report = service.complete_refactoring(str(project))

    assert report.phase is Phase.SCOPE_REQUIRED
    assert service.status(str(project)).phase is Phase.SCOPE_REQUIRED


def test_completing_is_refused_while_the_tests_fail(service, adapter, project):
    _to_refactoring(service, adapter, project)
    adapter.outcome = Outcome.FAILED

    with pytest.raises(RefactorError, match="tests must pass"):
        service.complete_refactoring(str(project))


def test_completing_is_refused_while_the_scope_lost_coverage(service, adapter, project):
    _to_refactoring(service, adapter, project)
    adapter.uncovered = {"invoice.code": frozenset({2})}

    with pytest.raises(RefactorError, match="no longer covered"):
        service.complete_refactoring(str(project))


def test_completing_is_refused_while_changed_lines_hold_comments(
    service, adapter, history, project
):
    """Say it with names: a comment is a smell the next refactoring inherits."""
    _to_refactoring(service, adapter, project)
    (project / "invoice.code").write_text("line one  # explains itself badly\n")
    history.changed = {"invoice.code": frozenset({1})}

    with pytest.raises(RefactorError, match="hold comments"):
        service.complete_refactoring(str(project))


def test_completing_is_refused_outside_refactoring(service, project):
    _declare(service, project)
    with pytest.raises(RefactorError, match="only while refactoring"):
        service.complete_refactoring(str(project))


def test_run_tests_never_changes_the_phase(service, adapter, project):
    adapter.uncovered = {"invoice.code": frozenset({2})}
    _to_refactoring(service, adapter, project)

    report = service.run_tests(str(project))

    assert report.phase is Phase.APPROVAL_TESTS
    assert "phase unchanged" in report.message


def test_run_tests_narrows_to_a_file_and_a_name(service, adapter, project):
    _to_refactoring(service, adapter, project)
    (project / "test_invoice").write_text("t")

    service.run_tests(str(project), "test_invoice", "pins")

    assert adapter.selections[-1] == ("test_invoice", "pins")


def test_run_tests_refuses_a_missing_path(service, adapter, project):
    _to_refactoring(service, adapter, project)
    with pytest.raises(RefactorError, match="does not exist"):
        service.run_tests(str(project), "ghost")


def test_run_tests_refuses_a_selection_that_looks_like_an_option(
    service, adapter, project
):
    _to_refactoring(service, adapter, project)
    with pytest.raises(RefactorError, match="must not start with '-'"):
        service.run_tests(str(project), None, "-p")


def test_a_non_code_file_is_written_without_running_the_tests(
    service, adapter, project
):
    _to_refactoring(service, adapter, project)
    before = adapter.test_runs

    report = service.write_file(str(project), "notes.md", "docs")

    assert adapter.test_runs == before
    assert "not code" in report.message


def test_an_exempt_file_skips_the_workflow(adapter, tree, history, project):
    service = RefactorService(
        {"fake": adapter},
        pending_changes=tree,
        history=history,
        exempt=["generated/*"],
    )
    _declare(service, project)
    service.check_coverage(str(project))

    report = service.write_file(str(project), "generated/stub.code", "generated")

    assert "exempt" in report.message
    assert (project / "generated" / "stub.code").read_text() == "generated"


def test_a_dirty_tree_with_no_open_step_blocks_an_edit(service, adapter, tree, project):
    """check_coverage ends the step, so leftover changes belong to nobody."""
    _to_refactoring(service, adapter, project)
    tree.changes = [" M invoice.code"]

    with pytest.raises(RefactorError, match="Commit them first"):
        service.edit_file(str(project), "invoice.code", "line one", "first line")


def test_the_commit_demand_names_the_refactoring_notation(
    service, adapter, tree, project
):
    _to_refactoring(service, adapter, project)
    tree.changes = [" M invoice.code"]

    with pytest.raises(RefactorError, match=r"'\. r' for a refactoring"):
        service.edit_file(str(project), "invoice.code", "line one", "first line")


def test_a_locked_file_reports_the_lock_before_the_commit_demand(
    service, adapter, tree, project
):
    """Committing can't unlock it, so asking for a commit first sends models in circles."""
    adapter.uncovered = {"invoice.code": frozenset({2})}
    _to_refactoring(service, adapter, project)
    tree.changes = [" M something"]

    with pytest.raises(RefactorError, match="not allowed in the approval_tests phase"):
        service.write_file(str(project), "invoice.code", "refactored")


def test_repeat_edits_within_one_step_are_allowed(service, adapter, tree, project):
    _to_refactoring(service, adapter, project)
    service.edit_file(str(project), "invoice.code", "line one", "first line")
    tree.changes = [" M invoice.code"]

    report = service.edit_file(str(project), "invoice.code", "first line", "the first")

    assert report.phase is Phase.REFACTORING
    assert (project / "invoice.code").read_text() == "the first\nline two\n"


def test_sessions_are_per_location(service, adapter, tmp_path):
    one, two = tmp_path / "one", tmp_path / "two"
    for root in (one, two):
        root.mkdir()
        (root / "invoice.code").write_text("x\n")
    _to_refactoring(service, adapter, one)

    assert service.status(str(one)).phase is Phase.REFACTORING
    assert service.status(str(two)).phase is Phase.SCOPE_REQUIRED


def test_a_report_renders_the_phase_first(service, adapter, project):
    report = _to_refactoring(service, adapter, project)
    assert report.render().startswith("Phase: refactoring")
    assert "coverage output" in report.render()


def test_a_refactoring_report_renders_the_rule(service, adapter, project):
    report = _to_refactoring(service, adapter, project)
    assert "Rule: intention" in report.render()


def test_output_is_tail_truncated(service, adapter, project):
    adapter.outcome = Outcome.PASSED
    report = Report(Phase.REFACTORING, "message", "x" * 10_000)
    assert len(report.render()) < 8_000


def test_a_report_without_output_renders_only_the_heading():
    assert Report(Phase.SCOPE_REQUIRED, "message").render() == (
        "Phase: scope_required\nmessage"
    )


def test_a_coverage_run_without_counts_keeps_the_test_baseline(
    adapter, tree, history, project
):
    """A runner that produced no report must not reset the count to zero."""
    service = RefactorService({"fake": adapter}, pending_changes=tree, history=history)
    adapter.counts = None
    _declare(service, project)

    assert service.check_coverage(str(project)).phase is Phase.REFACTORING


def test_a_later_phase_edit_is_refused_with_the_commit_demand(
    service, adapter, tree, project
):
    """The open step is approval_tests, so a production edit belongs to a later one."""
    adapter.uncovered = {"invoice.code": frozenset({2})}
    _to_refactoring(service, adapter, project)
    service.write_file(str(project), "test_invoice.approved.txt", "baseline")
    tree.changes = ["?? test_invoice.approved.txt"]
    adapter.uncovered = {}
    service.write_file(str(project), "test_invoice", "pins behaviour")

    with pytest.raises(RefactorError, match="Commit them first"):
        service.write_file(str(project), "invoice.code", "refactored")


def test_completing_skips_the_comment_check_when_the_base_was_rewound(
    service, adapter, history, project
):
    """After a reset past the scope's base, pre-reset lines are not this refactoring's."""
    _to_refactoring(service, adapter, project)
    (project / "invoice.code").write_text("line one  # a comment\n")
    history.changed = {"invoice.code": frozenset({1})}
    history.ancestor = False

    assert service.complete_refactoring(str(project)).phase is Phase.SCOPE_REQUIRED


def test_completing_ignores_comments_in_non_code_files(
    service, adapter, history, project
):
    _to_refactoring(service, adapter, project)
    (project / "notes.md").write_text("# a heading, not a code comment\n")
    history.changed = {"notes.md": frozenset({1})}

    assert service.complete_refactoring(str(project)).phase is Phase.SCOPE_REQUIRED


def test_completing_ignores_changed_lines_that_hold_no_comment(
    service, adapter, history, project
):
    _to_refactoring(service, adapter, project)
    history.changed = {"invoice.code": frozenset({1})}

    assert service.complete_refactoring(str(project)).phase is Phase.SCOPE_REQUIRED


def test_completing_without_history_skips_the_comment_check(adapter, tree, project):
    service = RefactorService({"fake": adapter}, pending_changes=tree)
    _declare(service, project)
    service.check_coverage(str(project))

    assert service.complete_refactoring(str(project)).phase is Phase.SCOPE_REQUIRED


def test_an_unmeasured_coverage_run_does_not_unlock_refactoring(
    service, adapter, project
):
    """An empty coverage report means no test ran the scope, not that it is safe."""
    adapter.measured = False
    _declare(service, project)

    report = service.check_coverage(str(project))

    assert report.phase is Phase.APPROVAL_TESTS
    assert "No coverage was measured" in report.message


def test_an_unmeasured_approval_run_does_not_unlock_refactoring(
    service, adapter, project
):
    adapter.uncovered = {"invoice.code": frozenset({2})}
    _to_refactoring(service, adapter, project)
    adapter.uncovered = {}
    adapter.measured = False

    report = service.write_file(str(project), "test_invoice", "pins nothing")

    assert report.phase is Phase.APPROVAL_TESTS


def test_completing_is_refused_when_coverage_stops_being_measured(
    service, adapter, project
):
    _to_refactoring(service, adapter, project)
    adapter.measured = False

    with pytest.raises(RefactorError, match="no longer covered"):
        service.complete_refactoring(str(project))
