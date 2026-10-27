# Contributing

## Setup

Install [mise](https://mise.jdx.dev/), then:

```bash
./build_and_test
```

That installs the pinned toolchain, syncs dependencies with `uv`, and runs the
suite with coverage. `mise run format` formats with `ruff`.

The TypeScript adapter's tests run a real `npm install` of vitest in a temp
directory, so the full suite takes a couple of minutes. While iterating, narrow
it: `uv run pytest tests/test_service.py -q`.

## Module layout

| Module | Responsibility |
|---|---|
| `phases.py` | the state machine: phases, rules, write permissions, transitions. Pure — no I/O |
| `scope.py` | which production files a refactoring covers, and whether tests reach all of it |
| `service.py` | orchestration: gates writes, runs tests, advances phases, builds replies |
| `server.py` | MCP bindings only, no logic |
| `workspace.py` | file operations confined to the project root, with snapshots so writes can be undone |
| `git_gate.py` | working-tree status, HEAD, and changed lines |
| `reports.py` | reading test runners' JUnit and coverage reports |
| `languages/` | per-language adapters behind a `Protocol` |

Keep `phases.py` free of I/O: it is exhaustively unit-testable precisely because
it only maps inputs to a `Transition`.

## Adding a language

1. Write an adapter satisfying `LanguageAdapter` in `languages/`. `classify`
   must return `FileKind.APPROVED` for baseline files, and `run_coverage` must
   set `measured=True` only when a coverage report was actually produced —
   otherwise an unmeasured scope would look fully covered.
2. Register it in `languages/__init__.py`. `LanguageName` is derived from the
   registry, so the published schema's enum updates automatically.
3. Re-approve the tool manifest: run the suite, then
   `mv tests/manifest.received.json tests/manifest.approved.json` after reading
   the diff.

## Conventions

- No code comments. Express intent through names, docstrings, and tests.
- Every phase's guidance names its own phase and ends with a concrete `Next:`
  step; `tests/test_phases.py` asserts this. The audience includes small local
  models, so refusals must say which tool call gets them unstuck.
- A state the agent can enter but no tool can leave is a design bug, not a
  wording problem. Reserve "ask the user" for causes outside the repository,
  such as a missing test runner.
- Coverage stays at 100%, lines and branches. Prefer deleting unreachable code
  to writing a test that reaches for it.
