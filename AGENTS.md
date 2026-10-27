# Agent Instructions

## Writing code in this repository

Write `.py` files only through the `refactor` MCP server: `declare_scope` →
`check_coverage` → approval test if needed → `edit_file` through the rules →
`complete_refactoring`. See the `refactor-cycle` skill in
`.claude/skills/refactor-cycle/`.

Call the server's tools strictly sequentially. Never send edits in parallel,
even to different files: concurrent edits race and silently drop all but one.

If the `refactor` tools aren't loaded in the session, drive the server over
stdio with an MCP client script rather than bypassing the workflow.

Register the server in both `.mcp.json` (Claude Code) and `.vscode/mcp.json`
(VS Code) when changing its invocation.

## Restarting after changes to the server

The running server keeps the code it was started with. After changing the
server's own source, ask the user to restart it before relying on the fix. When
the server behaves unlike the source, check whether the process predates the
relevant commit before debugging the code.

## Verifying external tool output

Before building on a test runner's or coverage tool's output, spike it in a temp
directory on the edge cases first: import errors, syntax errors, and above all
**empty suites**. An empty coverage report is the dangerous case here — it looks
identical to full coverage unless the adapter reports whether it measured
anything at all.

For anything that spawns test subprocesses, run the suite both with and without
`--cov`: timing differences expose caching and race bugs.

## Reviewing messages agents read

The audience includes small local models. Every phase and rule must state where
the agent is and the concrete next tool call. When reviewing a weaker model's
session log, find each refusal it retried and check that the message's `Next:`
step actually works from that state. If no tool can, say "stop and ask the user"
explicitly — but prefer removing the dead end: a state the agent can enter but
no tool can leave is a design bug, not a wording problem.

## Tests

- Coverage stays at 100%, lines and branches.
- Before relying on a new test, reread its assertions: one that can never fail
  is a false green.
- Don't add code comments; `complete_refactoring` refuses while a changed line
  holds one.
- Never add a reflection-based test.

## Security

- For tools that take a path, verify root confinement against `..`, absolute
  paths, and symlinks.
- Reject tool arguments starting with `-`: a test runner would parse them as
  options.
- Run `uv export --format requirements-txt --no-hashes --all-groups -o <tmp>`
  then `uvx pip-audit -r <tmp>` when changing dependencies.
