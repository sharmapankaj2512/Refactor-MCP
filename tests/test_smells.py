from refactor_mcp.phases import Rule
from refactor_mcp.smells import find_python_smells


def _findings(source: str, rule: Rule) -> str:
    return " | ".join(find_python_smells(source, rule))


def test_a_long_method_is_reported_for_intention():
    body = "\n".join(f"    x{n} = {n}" for n in range(15))
    source = f"def wide():\n{body}\n"
    assert "wide" in _findings(source, Rule.INTENTION)
    assert "long" in _findings(source, Rule.INTENTION).lower()


def test_a_short_method_is_not_reported():
    assert find_python_smells("def narrow():\n    return 1\n", Rule.INTENTION) == []


def test_a_magic_number_is_reported_for_intention():
    source = "def charge(amount):\n    return amount * 1.175\n"
    assert "1.175" in _findings(source, Rule.INTENTION)


def test_small_integers_are_not_magic():
    """0, 1, 2 and -1 read fine; flagging them is noise."""
    source = "def step(n):\n    return n + 1 - 1 + 0 + 2\n"
    assert find_python_smells(source, Rule.INTENTION) == []


def test_a_named_constant_is_not_magic():
    source = "RATE = 1.175\n\n\ndef charge(amount):\n    return amount * RATE\n"
    assert find_python_smells(source, Rule.INTENTION) == []


def test_a_cryptic_name_is_reported_for_intention():
    source = "def f(a, b):\n    return a + b\n"
    findings = _findings(source, Rule.INTENTION)
    assert "f" in findings
    assert "name" in findings.lower()


def test_a_repeated_statement_sequence_is_reported_for_duplication():
    source = (
        "def one(item):\n"
        "    item.sell_in -= 1\n"
        "    if item.sell_in < 0:\n"
        "        item.quality = 0\n"
        "\n\n"
        "def two(item):\n"
        "    item.sell_in -= 1\n"
        "    if item.sell_in < 0:\n"
        "        item.quality = 0\n"
    )
    findings = _findings(source, Rule.DUPLICATION)
    assert "one" in findings and "two" in findings
    assert "repeat" in findings.lower()


def test_distinct_statements_are_not_duplication():
    source = (
        "def one(item):\n    item.a = 1\n    item.b = 2\n"
        "\n\n"
        "def two(item):\n    item.c = 3\n    item.d = 4\n"
    )
    assert find_python_smells(source, Rule.DUPLICATION) == []


def test_a_single_shared_statement_is_not_duplication():
    """One repeated line is usually coincidence; two in sequence is a pattern."""
    source = "def one(x):\n    y = 1\n    return x\n\n\ndef two(x):\n    y = 1\n    return -x\n"
    assert find_python_smells(source, Rule.DUPLICATION) == []


def test_an_uncalled_private_method_is_reported_for_fewest_elements():
    source = (
        "class Thing:\n"
        "    def _used(self):\n        return 1\n\n"
        "    def _orphan(self):\n        return 2\n\n"
        "    def run(self):\n        return self._used()\n"
    )
    findings = _findings(source, Rule.FEWEST_ELEMENTS)
    assert "_orphan" in findings
    assert "`_used`" not in findings


def test_a_public_method_is_never_reported_as_dead():
    """Anything outside the module may call it, so its absence here proves nothing."""
    source = "class Thing:\n    def run(self):\n        return 1\n"
    assert find_python_smells(source, Rule.FEWEST_ELEMENTS) == []


def test_a_called_method_is_not_reported():
    source = (
        "class Thing:\n"
        "    def helper(self):\n        return 1\n\n"
        "    def run(self):\n        return self.helper()\n"
    )
    assert find_python_smells(source, Rule.FEWEST_ELEMENTS) == []


def test_a_module_level_function_is_never_dead_code():
    """It may be the public entry point; only the project knows, so don't guess."""
    source = "def maybe_an_entry_point():\n    return 1\n"
    assert find_python_smells(source, Rule.FEWEST_ELEMENTS) == []


def test_a_dunder_method_is_never_unused():
    source = "class Thing:\n    def __repr__(self):\n        return 'thing'\n"
    assert find_python_smells(source, Rule.FEWEST_ELEMENTS) == []


def test_an_unparseable_source_reports_nothing():
    """A syntax error is the test runner's job to report, not the detector's."""
    assert find_python_smells("def broken(:\n", Rule.INTENTION) == []


def test_findings_are_capped():
    body = "\n".join(f"def f{n}(a):\n    return a * 3.7\n\n" for n in range(20))
    assert len(find_python_smells(body, Rule.INTENTION)) <= 5


def test_repeated_control_flow_with_differing_bodies_is_duplication():
    """The Gilded Rose case: same scaffolding, different innards. The shape is the smell."""
    source = (
        "class Shop:\n"
        "    def _brie(self, item):\n"
        "        item.sell_in -= 1\n"
        "        if item.sell_in < 0:\n"
        "            self._raise(item)\n\n"
        "    def _ordinary(self, item):\n"
        "        item.sell_in -= 1\n"
        "        if item.sell_in < 0:\n"
        "            self._lower(item)\n"
    )
    findings = _findings(source, Rule.DUPLICATION)
    assert "_brie" in findings and "_ordinary" in findings


def test_different_control_flow_is_not_duplication():
    source = (
        "class Shop:\n"
        "    def _a(self, item):\n"
        "        item.sell_in -= 1\n"
        "        while item.quality:\n"
        "            item.quality -= 1\n\n"
        "    def _b(self, item):\n"
        "        item.quality += 1\n"
        "        return item\n"
    )
    assert find_python_smells(source, Rule.DUPLICATION) == []


def test_feature_envy_is_reported_for_intention():
    """A method that only ever touches its parameter belongs on that parameter."""
    source = (
        "class Shop:\n"
        "    def _raise_quality(self, item):\n"
        "        if item.quality < 50:\n"
        "            item.quality += 1\n"
    )
    findings = _findings(source, Rule.INTENTION)
    assert "_raise_quality" in findings
    assert "item" in findings
    assert "envy" in findings.lower()


def test_a_method_using_its_own_state_is_not_feature_envy():
    source = (
        "class Shop:\n"
        "    def total(self, item):\n"
        "        return self.rate * item.price\n"
    )
    assert find_python_smells(source, Rule.INTENTION) == []


def test_a_method_with_no_object_parameter_is_not_feature_envy():
    source = "class Shop:\n    def reset(self):\n        self.count = 0\n"
    assert find_python_smells(source, Rule.INTENTION) == []


def test_a_predicate_on_a_parameter_is_still_feature_envy():
    source = (
        "class Shop:\n"
        "    def _is_legendary(self, item):\n"
        "        return item.name == SULFURAS\n"
    )
    assert "_is_legendary" in _findings(source, Rule.INTENTION)


def test_primitive_obsession_is_reported_when_a_string_drives_branching():
    """A str compared against three constants is a type wearing a disguise."""
    source = (
        "class Shop:\n"
        "    def _update(self, item):\n"
        "        if item.name == AGED_BRIE:\n"
        "            return 1\n"
        "        elif item.name == BACKSTAGE_PASS:\n"
        "            return 2\n"
        "        elif item.name == SULFURAS:\n"
        "            return 3\n"
        "        return 4\n"
    )
    findings = _findings(source, Rule.INTENTION)
    assert "item.name" in findings
    assert "primitive obsession" in findings.lower()


def test_a_single_equality_check_is_not_primitive_obsession():
    """One comparison is a condition; several against constants is a missing type."""
    source = (
        "class Shop:\n"
        "    def _check(self, item):\n"
        "        if item.name == SULFURAS:\n"
        "            return self.rate\n"
        "        return 2\n"
    )
    findings = _findings(source, Rule.INTENTION)
    assert "primitive obsession" not in findings.lower()


def test_shotgun_surgery_is_reported_when_one_attribute_is_written_everywhere():
    """One concept edited in many places wants to own its own changes."""
    source = (
        "class Shop:\n"
        "    def a(self, item):\n        item.quality += 1\n"
        "    def b(self, item):\n        item.quality -= 1\n"
        "    def c(self, item):\n        item.quality = 0\n"
    )
    findings = _findings(source, Rule.DUPLICATION)
    assert "quality" in findings
    assert "shotgun" in findings.lower()


def test_an_attribute_written_in_one_place_is_not_shotgun_surgery():
    source = "class Shop:\n    def a(self, item):\n        item.quality += 1\n"
    assert find_python_smells(source, Rule.DUPLICATION) == []


def test_a_comparison_against_a_plain_name_is_not_primitive_obsession():
    """`x == A` three times is not a missing type; only an attribute of one object is."""
    source = (
        "class Shop:\n"
        "    def pick(self, kind):\n"
        "        if kind == A:\n            return self.a\n"
        "        if kind == B:\n            return self.b\n"
        "        if kind == C:\n            return self.c\n"
    )
    assert "primitive obsession" not in _findings(source, Rule.INTENTION).lower()


def test_writes_to_a_plain_local_are_not_shotgun_surgery():
    source = (
        "class Shop:\n"
        "    def a(self, item):\n        total = 1\n        return total + item.x\n"
        "    def b(self, item):\n        total = 2\n        return total + item.x\n"
        "    def c(self, item):\n        total = 3\n        return total + item.x\n"
    )
    assert "shotgun" not in _findings(source, Rule.DUPLICATION).lower()


def test_an_anaemic_data_class_is_reported_as_the_root_cause():
    """Four feature-envy symptoms have one cause: the class holds no behaviour."""
    source = (
        "class Item:\n"
        "    def __init__(self, name, quality):\n"
        "        self.name = name\n"
        "        self.quality = quality\n"
        "\n"
        "    def __repr__(self):\n"
        "        return self.name\n"
        "\n\n"
        "class Shop:\n"
        "    def _raise(self, item):\n"
        "        item.quality += 1\n"
        "\n"
        "    def _lower(self, item):\n"
        "        item.quality -= 1\n"
    )
    findings = _findings(source, Rule.INTENTION)
    assert "`Item`" in findings
    assert "anaemic" in findings.lower()


def test_a_class_with_behaviour_is_not_anaemic():
    source = (
        "class Item:\n"
        "    def __init__(self, quality):\n"
        "        self.quality = quality\n"
        "\n"
        "    def age(self):\n"
        "        self.quality -= 1\n"
        "\n\n"
        "class Shop:\n"
        "    def run(self, item):\n"
        "        item.age()\n"
    )
    assert "anaemic" not in _findings(source, Rule.INTENTION).lower()


def test_a_data_class_nobody_manipulates_is_not_anaemic():
    """A plain value holder is fine; the smell is behaviour living elsewhere."""
    source = (
        "class Point:\n"
        "    def __init__(self, x, y):\n"
        "        self.x = x\n"
        "        self.y = y\n"
    )
    assert "anaemic" not in _findings(source, Rule.INTENTION).lower()


def test_a_class_whose_only_methods_are_properties_is_still_anaemic():
    source = (
        "class Item:\n"
        "    def __init__(self, quality):\n"
        "        self.quality = quality\n"
        "\n"
        "    @property\n"
        "    def doubled(self):\n"
        "        return self.quality * 2\n"
        "\n\n"
        "class Shop:\n"
        "    def _bump(self, item):\n"
        "        item.quality += 1\n"
    )
    assert "anaemic" in _findings(source, Rule.INTENTION).lower()


def test_a_data_class_is_not_anaemic_when_other_classes_touch_only_their_own_data():
    """Writes elsewhere to *different* attributes are not this class's rules leaking."""
    source = (
        "class Point:\n"
        "    def __init__(self, x):\n"
        "        self.x = x\n"
        "\n\n"
        "class Counter:\n"
        "    def bump(self, other):\n"
        "        other.total += 1\n"
    )
    assert "anaemic" not in _findings(source, Rule.INTENTION).lower()
