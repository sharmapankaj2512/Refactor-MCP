import pytest

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


@pytest.mark.parametrize(
    ("phase", "kind", "allowed"),
    [
        (Phase.SCOPE_REQUIRED, FileKind.TEST, False),
        (Phase.SCOPE_REQUIRED, FileKind.PRODUCTION, False),
        (Phase.SCOPE_REQUIRED, FileKind.APPROVED, False),
        (Phase.SCOPE_REQUIRED, FileKind.OTHER, True),
        (Phase.COVERAGE_CHECK, FileKind.TEST, False),
        (Phase.COVERAGE_CHECK, FileKind.PRODUCTION, False),
        (Phase.COVERAGE_CHECK, FileKind.APPROVED, False),
        (Phase.COVERAGE_CHECK, FileKind.OTHER, True),
        (Phase.APPROVAL_TESTS, FileKind.TEST, True),
        (Phase.APPROVAL_TESTS, FileKind.PRODUCTION, False),
        (Phase.APPROVAL_TESTS, FileKind.APPROVED, True),
        (Phase.APPROVAL_TESTS, FileKind.OTHER, True),
        (Phase.REFACTORING, FileKind.TEST, True),
        (Phase.REFACTORING, FileKind.PRODUCTION, True),
        (Phase.REFACTORING, FileKind.APPROVED, False),
        (Phase.REFACTORING, FileKind.OTHER, True),
    ],
)
def test_may_write(phase, kind, allowed):
    assert may_write(phase, kind) is allowed


def test_production_code_is_locked_until_refactoring():
    """The whole point of the server: behaviour must be pinned before code moves."""
    locked = [phase for phase in Phase if not may_write(phase, FileKind.PRODUCTION)]
    assert locked == [Phase.SCOPE_REQUIRED, Phase.COVERAGE_CHECK, Phase.APPROVAL_TESTS]


def test_approved_files_are_writable_only_while_writing_approval_tests():
    """A baseline is created in approval_tests and frozen from then on."""
    writable = [phase for phase in Phase if may_write(phase, FileKind.APPROVED)]
    assert writable == [Phase.APPROVAL_TESTS]


def test_every_phase_names_itself_and_the_next_step():
    """Weaker models lose track of the workflow, so every reply restates where they are."""
    for phase in Phase:
        guidance = PHASE_GUIDANCE[phase]
        assert f"You are in the {phase} phase." in guidance
        assert "Next:" in guidance


def test_every_rule_names_itself_and_the_smells_to_hunt():
    """Weaker models skim the rules, so each one states its number and its targets."""
    for rule in Rule:
        guidance = RULE_GUIDANCE[rule]
        assert rule.value.replace("_", " ") in guidance.lower()
        assert "hunt" in guidance.lower()
        assert "Next:" in guidance


@pytest.mark.parametrize(
    ("rule", "number"),
    [
        (Rule.INTENTION, "Rule 2"),
        (Rule.DUPLICATION, "Rule 3"),
        (Rule.FEWEST_ELEMENTS, "Rule 4"),
    ],
)
def test_each_rule_states_its_number_in_kent_becks_list(rule, number):
    assert RULE_GUIDANCE[rule].startswith(number)


@pytest.mark.parametrize(
    ("rule", "outranked_by"),
    [
        (Rule.DUPLICATION, ["rule 1", "rule 2"]),
        (Rule.FEWEST_ELEMENTS, ["rule 1", "rule 2", "rule 3"]),
    ],
)
def test_each_rule_names_the_higher_rules_it_yields_to(rule, outranked_by):
    """Asserting only the word 'never' was a meta-test that could not fail."""
    guidance = RULE_GUIDANCE[rule].lower()
    for higher in outranked_by:
        assert higher in guidance


def test_the_top_ranked_rule_yields_only_to_passing_tests():
    assert "rule 1" in RULE_GUIDANCE[Rule.INTENTION].lower()


@pytest.mark.parametrize(
    ("covered", "expected"),
    [(True, Phase.REFACTORING), (False, Phase.APPROVAL_TESTS)],
)
def test_after_coverage_check(covered, expected):
    assert after_coverage_check(covered) is expected


def test_approval_test_that_passes_and_covers_the_scope_unlocks_refactoring():
    transition = after_approval_write(Outcome.PASSED, scope_covered=True, added=1)
    assert transition.phase is Phase.REFACTORING
    assert transition.revert is False


def test_approval_test_that_leaves_gaps_stays_in_approval_tests():
    transition = after_approval_write(Outcome.PASSED, scope_covered=False, added=1)
    assert transition.phase is Phase.APPROVAL_TESTS
    assert "not covered" in transition.reason


def test_failing_approval_test_cannot_pin_behaviour():
    transition = after_approval_write(Outcome.FAILED, scope_covered=True, added=1)
    assert transition.phase is Phase.APPROVAL_TESTS
    assert "must pass" in transition.reason


def test_approval_test_run_that_errors_stays_in_approval_tests():
    transition = after_approval_write(Outcome.ERROR, scope_covered=True, added=1)
    assert transition.phase is Phase.APPROVAL_TESTS
    assert "could not be collected or run" in transition.reason


@pytest.mark.parametrize(
    ("outcome", "kind", "revert"),
    [
        (Outcome.PASSED, FileKind.PRODUCTION, False),
        (Outcome.PASSED, FileKind.TEST, False),
        (Outcome.FAILED, FileKind.PRODUCTION, True),
        (Outcome.ERROR, FileKind.PRODUCTION, True),
    ],
)
def test_after_refactor_write(outcome, kind, revert):
    transition = after_refactor_write(outcome, kind, added=0)
    assert transition.phase is Phase.REFACTORING
    assert transition.revert is revert


def test_a_refactoring_that_breaks_the_tests_is_reverted():
    transition = after_refactor_write(Outcome.FAILED, FileKind.PRODUCTION, added=0)
    assert transition.revert is True
    assert "must keep the tests passing" in transition.reason


def test_a_refactoring_that_adds_a_test_is_reverted():
    transition = after_refactor_write(Outcome.PASSED, FileKind.TEST, added=1)
    assert transition.revert is True
    assert "new behaviour" in transition.reason


def test_rewriting_an_approved_file_is_reverted():
    """Re-approving the baseline is the one way to fake a green approval test."""
    transition = after_refactor_write(Outcome.PASSED, FileKind.APPROVED, added=0)
    assert transition.revert is True
    assert "behavioural baseline" in transition.reason


def test_a_disallowed_write_is_rejected():
    with pytest.raises(ValueError, match="not allowed"):
        after_approval_write(
            Outcome.PASSED, scope_covered=True, added=1, kind=FileKind.PRODUCTION
        )


def test_non_code_writes_cannot_advance_the_workflow():
    with pytest.raises(ValueError, match="only code files"):
        after_refactor_write(Outcome.PASSED, FileKind.OTHER, added=0)


def test_a_non_code_approval_write_cannot_advance_the_workflow():
    with pytest.raises(ValueError, match="only code files"):
        after_approval_write(
            Outcome.PASSED, scope_covered=True, added=1, kind=FileKind.OTHER
        )


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        (Rule.INTENTION, Rule.DUPLICATION),
        (Rule.DUPLICATION, Rule.FEWEST_ELEMENTS),
        (Rule.FEWEST_ELEMENTS, None),
    ],
)
def test_next_rule(rule, expected):
    assert next_rule(rule) is expected


def test_the_rules_run_in_kent_becks_priority_order():
    assert list(Rule) == [Rule.INTENTION, Rule.DUPLICATION, Rule.FEWEST_ELEMENTS]


@pytest.mark.parametrize(
    ("rule", "smell"),
    [
        (Rule.INTENTION, "feature envy"),
        (Rule.INTENTION, "primitive obsession"),
        (Rule.DUPLICATION, "shotgun surgery"),
    ],
)
def test_guidance_names_the_smells_the_detector_can_find(rule, smell):
    """Guidance that names only undetectable smells reads as boilerplate to skim."""
    assert smell in RULE_GUIDANCE[rule].lower()


def test_intention_warns_that_extracting_methods_is_not_enough():
    """The failure mode this server hit: small methods that all poke one object."""
    assert "not enough" in RULE_GUIDANCE[Rule.INTENTION].lower()
