---
name: refactor-cycle
description: Use when changing code in a repository that has the `refactor` MCP server configured — how to drive declare_scope / check_coverage / write_file / edit_file / next_rule / complete_refactoring, and what to do when a write is refused or reverted.
version: 1.0.0
---

# Driving the refactor MCP server

This skill is about *operating the tools*, not about refactoring theory. The
server decides what you may write; your job is to work with it rather than
around it.

## The loop

1. **`declare_scope(location, paths)`** — the production files you intend to
   change. Folders expand to the production files inside them. A scope of only
   tests or docs is refused: the scope is what gets pinned.
2. **`check_coverage(location)`** — runs the whole suite with branch coverage.
   - Fully covered → `refactoring`, rule `intention`. Start editing.
   - Anything uncovered → `approval_tests`, with the missing lines named.
3. **`approval_tests`** — write ONE test that records what the code does today.
   Production code is locked here; don't retry it. Call the scope as a caller
   does, capture the result, approve it. Assert current behaviour, bugs
   included.
4. **`refactoring`** — `edit_file` in small steps, committing each through the
   `racn` server's `commit` tool (`risk=proven_safe, intention=refactoring`).
   `next_rule` to move through `intention` → `duplication` → `fewest_elements`.
   Each rule's guidance lists concrete targets found in your scope; work them,
   because `next_rule` refuses while a rule has changed nothing. Use
   `skip_rule` with a reason when the code already satisfies a rule.
5. **`complete_refactoring(location)`** — verifies suite, coverage and comments,
   then returns to `scope_required`.

## When refused or reverted

| What you see | What it means | What to do |
|---|---|---|
| `No refactoring started` | No scope for this location | `declare_scope` first |
| `not allowed in the approval_tests phase` | Production code is locked until behaviour is pinned | Write the approval test; do not retry the edit |
| `No test exercises <file> at all` | That file is absent from the coverage report | Write an approval test that imports and calls it; absent is unmeasured, not covered |
| `Lines in the scope are not covered` | Partial coverage | Extend the approval test to reach those lines |
| `An approval test must pass` | The test asserts behaviour the code doesn't have | Match the test to today's behaviour, not the desired one |
| `was reverted` + `must keep the tests passing` | Your edit changed behaviour | Make a smaller change: one rename, one extraction, one move |
| `was reverted` + `must not add tests` | You added a test while refactoring | New behaviour needs a TDD cycle; finish refactoring first |
| `behavioural baseline` | You tried to rewrite an `*.approved.*` file | Don't. If the baseline is wrong, that's a behaviour change |
| `Commit them first` | An earlier step is uncommitted | `git add` then commit (`. t` / `. r`), sequentially, then retry |
| `The tests must pass before moving on` | `next_rule` while red | Fix or undo the last change first |
| `hold comments` | A changed line has a comment | Delete it; let names carry the meaning |
| `Rule fewest_elements is the last rule` | Nothing left to advance to | Call `complete_refactoring` |
| `changed no production code` | This rule did nothing, so it was not applied | Make one edit for it, or `skip_rule` with a reason if the code already satisfies it |
| `Skipping a rule needs a reason` | The reason was too short to be meaningful | Say why the code already satisfies the rule, in a sentence |

## Pitfalls

- **Don't retry a locked write.** If production code is locked, no number of
  retries unlocks it; the phase does. Read the `Next:` sentence.
- **A rename is not automatically safe.** Renaming a parameter without renaming
  its uses breaks the tests and gets reverted. Change all occurrences in one
  `edit_file`, or pick a smaller edit.
- **`edit_file` needs a unique `old_string`.** A refusal naming a match count
  means add surrounding lines until it's unique.
- **Never send edits in parallel.** Concurrent edits to one file race and
  silently drop all but one. One call at a time.
- **Commit and edit are separate steps.** Run `git add` and the commit
  sequentially, never batched with the next edit.
- **After changing the server's own code, restart it.** A running server keeps
  the source it started with; otherwise you'll debug behaviour that no longer
  exists in the file.
- **`run_tests` unlocks nothing.** Only `check_coverage` and the runs that
  `write_file`/`edit_file` trigger move the workflow.
- **Coverage includes branches.** An `if` whose false path no test takes counts
  as uncovered, so the approval test may need more than one case.
- **Advancing a rule is not applying it.** Calling `next_rule` three times in a
  row leaves the refactoring unfinished; the server now refuses this, but the
  habit is the thing to avoid. Read the targets it lists and fix them.
- **An unrelated passing test proves nothing.** The suite can be green and the
  report valid while your scope is missing from it entirely. The server checks
  that each scope file was actually measured, so don't expect a green suite to
  unlock refactoring by itself.
