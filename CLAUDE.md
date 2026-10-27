# Writing code

Always use the `refactor` MCP server's `write_file` / `edit_file` tools to change
`.py` files in this repository. Built-in editing of Python files is blocked.

Start each scope with `declare_scope`, then `check_coverage`. Write one approval
test if anything is uncovered, then refactor through the rules of simple design
with `next_rule`, and finish with `complete_refactoring`. Call `refactor_status`
if unsure what the current phase allows.

New behaviour is not refactoring: this server reverts any edit that adds a test.
Use a test-driven cycle for that.

# Committing

Commit every step separately: an approval test as `. t`, each refactoring as
`. r`. The server refuses the next step's edits until the previous one is
committed; repeat edits within one step are allowed.

# Notes

- Don't add code comments. `complete_refactoring` refuses while any line changed
  during the refactoring holds one (tool directives excepted). Express intent
  through names, docstrings, and tests.
- The running server keeps the code it was started with. After changing the
  server's own source, ask for a restart before relying on the fix.
- An empty coverage report means *unmeasured*, not *covered*. Never treat a
  scope no test touches as safe to refactor.

See [README.md](README.md) for the full workflow and registration.
