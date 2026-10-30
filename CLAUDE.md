# Writing code

Always use the `refactor` MCP server's `write_file` / `edit_file` tools to change
`.py` files in this repository. Built-in editing of Python files is blocked.

Start each scope with `declare_scope`, then `check_coverage`. Write one approval
test if anything is uncovered, then refactor through the rules of simple design
with `next_rule`, and finish with `complete_refactoring`. Call `refactor_status`
if unsure what the current phase allows.

Each rule must do real work: `next_rule` refuses while the current rule has
changed no production code, and names the concrete targets it found in the
scope. If the code already satisfies a rule, `skip_rule` with a reason — it is
recorded and shown when the refactoring completes.

New behaviour is not refactoring: this server reverts any edit that adds a test.
Use a test-driven cycle for that.

# Committing

Commit every step separately, through the `racn` MCP server's `commit` tool:
`risk=proven_safe, intention=test_only` for an approval test, and
`risk=proven_safe, intention=refactoring` for a refactoring. Don't hand-write
the notation — the tool generates and validates it. The server refuses the next step's edits until the previous one is
committed; repeat edits within one step are allowed.

# Notes

- Don't add code comments. `complete_refactoring` refuses while any line changed
  during the refactoring holds one (tool directives excepted). Express intent
  through names, docstrings, and tests.
- The running server keeps the code it was started with. After changing the
  server's own source, ask for a restart before relying on the fix.
- "Covered" means measured *and* gapless. A file absent from the coverage
  report has no uncovered lines, so it mimics full coverage; `Scope.is_covered`
  requires every scope file to appear in the report. Never treat a scope no test
  touches as safe to refactor.

See [README.md](README.md) for the full workflow and registration.
