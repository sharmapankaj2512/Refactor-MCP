"""Cheap, line-anchored smell detection, so a rule names real targets instead of categories."""

from __future__ import annotations

import ast
from collections import defaultdict

from refactor_mcp.phases import Rule

MAX_FINDINGS = 5
LONG_METHOD_STATEMENTS = 12
READABLE_NUMBERS = frozenset({0, 1, 2, -1, -2, 100})
MIN_NAME_LENGTH = 3
BRANCHING_COMPARISONS = 3
SCATTERED_WRITES = 3
SEQUENCE_LENGTH = 2
# Short names that are conventional rather than cryptic.
IDIOMATIC_NAMES = frozenset({"self", "cls", "n", "i", "j", "k", "x", "y", "z", "_"})


def find_python_smells(source: str, rule: Rule) -> list[str]:
    """Concrete targets for `rule` in `source`, most specific first, capped."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    findings = _DETECTORS[rule](tree)
    return findings[:MAX_FINDINGS]


def _intention(tree: ast.AST) -> list[str]:
    return (
        _feature_envy(tree)
        + _primitive_obsession(tree)
        + _long_methods(tree)
        + _magic_numbers(tree)
        + _cryptic_names(tree)
    )


def _feature_envy(tree: ast.AST) -> list[str]:
    """Methods that only ever touch one parameter: the behaviour belongs on it."""
    findings = []
    for node in _methods(tree):
        parameters = [a.arg for a in node.args.args[1:]]
        if not parameters:
            continue
        touched = {
            value.value.id
            for value in ast.walk(node)
            if isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name)
        }
        envied = [name for name in parameters if name in touched]
        if len(touched) == 1 and envied and "self" not in touched:
            findings.append(
                f"line {node.lineno}: `{node.name}` only touches `{envied[0]}` — "
                f"feature envy: move it onto {envied[0]}"
            )
    return findings


def _primitive_obsession(tree: ast.AST) -> list[str]:
    """A primitive compared against several constants is a type in disguise."""
    compared: dict[str, list[int]] = defaultdict(list)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or not _is_equality(node):
            continue
        if isinstance(node.left, ast.Attribute) and isinstance(
            node.left.value, ast.Name
        ):
            name = f"{node.left.value.id}.{node.left.attr}"
            compared[name].append(node.lineno)
    return [
        f"line {lines[0]}: `{name}` is compared against "
        f"{len(lines)} constants — primitive obsession: give the concept its "
        "own type and let it answer for itself"
        for name, lines in compared.items()
        if len(lines) >= BRANCHING_COMPARISONS
    ]


def _is_equality(node: ast.Compare) -> bool:
    return any(isinstance(op, ast.Eq | ast.NotEq) for op in node.ops)


def _long_methods(tree: ast.AST) -> list[str]:
    return [
        f"line {node.lineno}: `{node.name}` is long "
        f"({count} statements) — extract the steps it takes"
        for node in _functions(tree)
        if (count := sum(1 for _ in ast.walk(node) if isinstance(_, ast.stmt)))
        > LONG_METHOD_STATEMENTS
    ]


def _magic_numbers(tree: ast.AST) -> list[str]:
    named = _named_constant_lines(tree)
    return [
        f"line {node.lineno}: magic number `{node.value}` — give it a name"
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, int | float)
        and not isinstance(node.value, bool)
        and node.value not in READABLE_NUMBERS
        and node.lineno not in named
    ]


def _named_constant_lines(tree: ast.AST) -> frozenset[int]:
    """Lines of module-level `NAME = <number>`, which is the fix, not the smell."""
    lines = set()
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            lines.add(node.value.lineno)
    return frozenset(lines)


def _cryptic_names(tree: ast.AST) -> list[str]:
    findings = []
    for node in _functions(tree):
        short = [
            name
            for name in [node.name] + [a.arg for a in node.args.args]
            if len(name) < MIN_NAME_LENGTH and name not in IDIOMATIC_NAMES
        ]
        if short:
            findings.append(
                f"line {node.lineno}: cryptic name(s) {', '.join(f'`{n}`' for n in short)}"
                " — say what they mean"
            )
    return findings


def _duplication(tree: ast.AST) -> list[str]:
    return _shotgun_surgery(tree) + _repeated_sequences(tree)


def _shotgun_surgery(tree: ast.AST) -> list[str]:
    """One attribute written from many places: the concept should own its changes."""
    written: dict[str, set[str]] = defaultdict(set)
    for node in _methods(tree):
        for assigned in ast.walk(node):
            targets = _written_targets(assigned)
            for target in targets:
                if isinstance(target, ast.Attribute) and isinstance(
                    target.value, ast.Name
                ):
                    written[f"{target.value.id}.{target.attr}"].add(node.name)
    return [
        f"`{name}` is written from {len(places)} methods "
        f"({', '.join(f'`{place}`' for place in sorted(places))}) — "
        "shotgun surgery: let it own its own changes"
        for name, places in written.items()
        if len(places) >= SCATTERED_WRITES
    ]


def _written_targets(node: ast.AST) -> list[ast.expr]:
    if isinstance(node, ast.Assign):
        return list(node.targets)
    if isinstance(node, ast.AugAssign):
        return [node.target]
    return []


def _methods(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Functions defined directly inside a class."""
    methods = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            methods += [
                child
                for child in node.body
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
            ]
    return methods


def _repeated_sequences(tree: ast.AST) -> list[str]:
    windows: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for node in _functions(tree):
        body = node.body
        for start in range(len(body) - SEQUENCE_LENGTH + 1):
            window = body[start : start + SEQUENCE_LENGTH]
            key = "\n".join(_shape(statement) for statement in window)
            windows[key].append((node.name, window[0].lineno))
    findings = []
    for places in windows.values():
        if len({name for name, _ in places}) < 2:
            continue
        where = ", ".join(f"`{name}` (line {line})" for name, line in places)
        findings.append(
            f"{SEQUENCE_LENGTH} statements repeat in {where} — name what they share"
        )
    return findings


def _fewest_elements(tree: ast.AST) -> list[str]:
    defined = {node.name: node.lineno for node in _nested_functions(tree)}
    used = {
        node.id if isinstance(node, ast.Name) else node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Name | ast.Attribute)
    }
    return [
        f"line {line}: `{name}` is private and never called here — delete it"
        for name, line in sorted(defined.items(), key=lambda pair: pair[1])
        if name not in used and _is_private(name)
    ]


def _is_private(name: str) -> bool:
    """Only a single-underscore name is certainly local: public and dunder
    methods can be called from anywhere, so their absence here proves nothing."""
    return name.startswith("_") and not name.startswith("__")


def _nested_functions(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Definitions inside a class or function: unlike module-level ones, these
    have no outside caller, so nothing referencing them means dead code."""
    nested = []
    for parent in ast.walk(tree):
        if not isinstance(
            parent, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ):
            continue
        nested += [
            child
            for child in parent.body
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
        ]
    return nested


def _functions(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]


def _shape(statement: ast.stmt) -> str:
    """A statement's own structure, excluding any nested block it controls.

    Duplicated scaffolding usually guards differing detail — `if x < 0:` around
    one call here and another there — so comparing whole subtrees would miss it.
    """
    outline = type(statement).__name__
    for field, value in ast.iter_fields(statement):
        if _is_block(value):
            continue
        outline += f"|{field}={_summarise(value)}"
    return outline


def _is_block(value: object) -> bool:
    return isinstance(value, list) and any(
        isinstance(element, ast.stmt) for element in value
    )


def _summarise(value: object) -> str:
    if isinstance(value, ast.AST):
        return ast.dump(value, annotate_fields=False, include_attributes=False)
    if isinstance(value, list):
        return ",".join(_summarise(element) for element in value)
    return repr(value)


_DETECTORS = {
    Rule.INTENTION: _intention,
    Rule.DUPLICATION: _duplication,
    Rule.FEWEST_ELEMENTS: _fewest_elements,
}
