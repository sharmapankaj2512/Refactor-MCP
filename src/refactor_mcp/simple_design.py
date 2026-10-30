"""Kent Beck's rules of simple design as a priority order, with rules 2 and 3 as a loop.

The rules are not phases you pass through. They are a tie-breaker consulted at
every decision: among designs that pass the tests, prefer the one that reveals
intention; among those, the one without duplication; among those, the one with
fewest elements.

Rules 2 and 3 feed each other. Naming a concept exposes the duplication it was
hiding, and removing duplication creates an abstraction that needs a name. So
they iterate until both are clean at the same moment, and only then does rule 4
(fewest elements) apply — deleting elements while duplication remains hides it
rather than removing it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from refactor_mcp.phases import Rule

# Highest priority first. A lower rule never justifies breaking a higher one.
PRIORITY: tuple[Rule, ...] = (Rule.INTENTION, Rule.DUPLICATION, Rule.FEWEST_ELEMENTS)

# The two rules that generate work for each other.
LOOP: frozenset[Rule] = frozenset({Rule.INTENTION, Rule.DUPLICATION})


@dataclass(frozen=True)
class Targets:
    """What each rule can still see in the scope."""

    by_rule: Mapping[Rule, Sequence[str]]

    def count(self, rule: Rule) -> int:
        return len(self.by_rule.get(rule, ()))

    def listing(self, rule: Rule) -> Sequence[str]:
        return self.by_rule.get(rule, ())


def outstanding(targets: Targets) -> list[Rule]:
    """Rules with work left, highest priority first."""
    return [rule for rule in PRIORITY if targets.count(rule)]


def loop_settled(targets: Targets) -> bool:
    """Whether rules 2 and 3 are clean at the same moment, the loop's fixpoint."""
    return not any(targets.count(rule) for rule in LOOP)


def rule_four_unlocked(targets: Targets) -> bool:
    return loop_settled(targets)


def conflicts(before: Targets, after: Targets) -> str | None:
    """Whether a change bought a lower-ranked rule by spending a higher-ranked one."""
    for spent_rank, spent in enumerate(PRIORITY):
        if after.count(spent) <= before.count(spent):
            continue
        for bought in PRIORITY[spent_rank + 1 :]:
            if after.count(bought) < before.count(bought):
                return (
                    f"This removed {bought} at the cost of {spent}: "
                    f"{spent} outranks {bought}, so a lower rule never justifies "
                    f"breaking a higher one. Fix the {spent} it introduced "
                    f"({', '.join(after.listing(spent))}), or leave the "
                    f"{bought} alone."
                )
    return None
