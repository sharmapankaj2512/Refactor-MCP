import pytest

from refactor_mcp.phases import Rule
from refactor_mcp.simple_design import (
    Targets,
    conflicts,
    loop_settled,
    outstanding,
    rule_four_unlocked,
)


def _targets(intention: int = 0, duplication: int = 0, elements: int = 0) -> Targets:
    return Targets(
        {
            Rule.INTENTION: tuple(f"i{n}" for n in range(intention)),
            Rule.DUPLICATION: tuple(f"d{n}" for n in range(duplication)),
            Rule.FEWEST_ELEMENTS: tuple(f"e{n}" for n in range(elements)),
        }
    )


def test_the_loop_runs_while_intention_has_targets():
    assert loop_settled(_targets(intention=1)) is False


def test_the_loop_runs_while_duplication_has_targets():
    assert loop_settled(_targets(duplication=1)) is False


def test_the_loop_settles_only_when_both_rules_are_clean_at_once():
    """Measured in the kata: intention cleared, duplication then appeared."""
    assert loop_settled(_targets(intention=0, duplication=0)) is True


def test_outstanding_elements_do_not_hold_the_loop_open():
    """Rule 4 is a separate step; it must not keep the 2<->3 loop spinning."""
    assert loop_settled(_targets(elements=3)) is True


def test_rule_four_is_locked_until_the_loop_settles():
    assert rule_four_unlocked(_targets(duplication=1)) is False


def test_rule_four_unlocks_at_the_fixpoint():
    assert rule_four_unlocked(_targets()) is True


def test_outstanding_reports_the_highest_ranked_rule_first():
    """The rules are a priority order, so the top-ranked target is the one to work."""
    assert outstanding(_targets(intention=1, duplication=1, elements=1))[0] is (
        Rule.INTENTION
    )


def test_outstanding_skips_satisfied_rules():
    assert outstanding(_targets(duplication=2)) == [Rule.DUPLICATION]


def test_nothing_is_outstanding_when_every_rule_is_clean():
    assert outstanding(_targets()) == []


def test_removing_duplication_at_the_cost_of_intention_is_a_conflict():
    before = _targets(intention=0, duplication=2)
    after = _targets(intention=1, duplication=0)

    assert conflicts(before, after) is not None
    assert "intention" in conflicts(before, after)


def test_the_conflict_names_which_rule_wins():
    before = _targets(intention=0, duplication=2)
    after = _targets(intention=1, duplication=0)

    assert "outranks" in conflicts(before, after)


def test_removing_elements_at_the_cost_of_duplication_is_a_conflict():
    before = _targets(duplication=0, elements=2)
    after = _targets(duplication=1, elements=0)

    assert "duplication" in conflicts(before, after)


def test_improving_a_higher_rule_at_the_cost_of_a_lower_one_is_no_conflict():
    """Intention outranks duplication, so paying duplication for a name is allowed."""
    before = _targets(intention=2, duplication=0)
    after = _targets(intention=0, duplication=1)

    assert conflicts(before, after) is None


def test_improving_everything_is_no_conflict():
    assert conflicts(_targets(intention=2, duplication=2), _targets()) is None


def test_an_unchanged_scope_is_no_conflict():
    assert conflicts(_targets(intention=1), _targets(intention=1)) is None
