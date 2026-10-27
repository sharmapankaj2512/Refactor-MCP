from pathlib import Path, PurePath

import pytest

from refactor_mcp.phases import FileKind
from refactor_mcp.scope import Scope, ScopeError, expand, listing, uncovered_in_scope


class FakeAdapter:
    """`test*` files are tests, `*.code` files are production, the rest is other."""

    name = "fake"

    def classify(self, relative_path: PurePath) -> FileKind:
        if relative_path.name.startswith("test"):
            return FileKind.TEST
        if relative_path.suffix == ".code":
            return FileKind.PRODUCTION
        return FileKind.OTHER


@pytest.fixture
def adapter() -> FakeAdapter:
    return FakeAdapter()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "billing").mkdir()
    (tmp_path / "billing" / "invoice.code").write_text("a\nb\n")
    (tmp_path / "billing" / "tax.code").write_text("c\n")
    (tmp_path / "billing" / "notes.md").write_text("docs\n")
    (tmp_path / "test_billing.code").write_text("t\n")
    return tmp_path


def test_a_single_file_becomes_the_scope(project, adapter):
    assert expand(project, ["billing/invoice.code"], adapter) == frozenset(
        {"billing/invoice.code"}
    )


def test_a_directory_expands_to_its_production_files(project, adapter):
    assert expand(project, ["billing"], adapter) == frozenset(
        {"billing/invoice.code", "billing/tax.code"}
    )


def test_expanding_a_directory_skips_non_production_files(project, adapter):
    assert "billing/notes.md" not in expand(project, ["billing"], adapter)


def test_expanding_a_directory_skips_test_files(project, adapter):
    """Refactoring a test file is allowed, but a scope is what gets pinned."""
    assert expand(project, ["."], adapter) == frozenset(
        {"billing/invoice.code", "billing/tax.code"}
    )


def test_several_paths_merge_into_one_scope(project, adapter):
    scope = expand(project, ["billing/invoice.code", "billing/tax.code"], adapter)
    assert scope == frozenset({"billing/invoice.code", "billing/tax.code"})


def test_a_scope_with_no_production_file_is_refused(project, adapter):
    with pytest.raises(ScopeError, match="no production code"):
        expand(project, ["billing/notes.md"], adapter)


def test_an_empty_path_list_is_refused(project, adapter):
    with pytest.raises(ScopeError, match="at least one path"):
        expand(project, [], adapter)


def test_a_missing_path_is_refused(project, adapter):
    with pytest.raises(ScopeError, match="does not exist"):
        expand(project, ["billing/ghost.code"], adapter)


def test_a_path_outside_the_project_is_refused(project, adapter):
    with pytest.raises(ValueError, match="outside the project root"):
        expand(project, ["../escape.code"], adapter)


def test_an_absolute_path_outside_the_project_is_refused(project, adapter):
    with pytest.raises(ValueError, match="outside the project root"):
        expand(project, ["/etc/passwd"], adapter)


def test_a_symlink_leading_outside_the_project_is_refused(
    project, adapter, tmp_path_factory
):
    outside = tmp_path_factory.mktemp("outside")
    (outside / "secret.code").write_text("x\n")
    (project / "link.code").symlink_to(outside / "secret.code")
    with pytest.raises(ValueError, match="outside the project root"):
        expand(project, ["link.code"], adapter)


def test_uncovered_lines_inside_the_scope_are_reported():
    scope = Scope(paths=frozenset({"a.code"}), base="abc")
    uncovered = {"a.code": frozenset({4, 9}), "b.code": frozenset({2})}
    assert uncovered_in_scope(scope, uncovered) == {"a.code": frozenset({4, 9})}


def test_uncovered_lines_outside_the_scope_are_ignored():
    """Legacy gaps elsewhere are not this refactoring's problem."""
    scope = Scope(paths=frozenset({"a.code"}), base="abc")
    assert uncovered_in_scope(scope, {"b.code": frozenset({2})}) == {}


def test_a_fully_covered_scope_reports_nothing():
    scope = Scope(paths=frozenset({"a.code"}), base="abc")
    assert uncovered_in_scope(scope, {}) == {}


def test_a_scope_is_fully_covered_when_nothing_is_uncovered():
    scope = Scope(paths=frozenset({"a.code"}), base="abc")
    assert scope.is_covered({}) is True


def test_a_scope_with_an_uncovered_line_is_not_fully_covered():
    scope = Scope(paths=frozenset({"a.code"}), base="abc")
    assert scope.is_covered({"a.code": frozenset({3})}) is False


def test_listing_sorts_paths_and_line_numbers():
    text = listing({"b.code": frozenset({3, 1}), "a.code": frozenset({2})})
    assert text == "a.code: 2; b.code: 1, 3"


def test_a_scope_renders_its_paths_in_a_stable_order():
    scope = Scope(paths=frozenset({"b.code", "a.code"}), base="abc")
    assert scope.render() == "a.code, b.code"
