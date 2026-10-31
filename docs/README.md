# Docs

Two standalone HTML pages. Open them directly in a browser — no build step, no
dependencies beyond a webfont link. Diagrams are Mermaid, rendered natively by
the Artifact runtime; in a plain browser they appear as their source text.

| Page | Covers |
|---|---|
| [`state-machine.html`](state-machine.html) | The four phases, the write-permission table, the rules 2↔3 loop and its fixpoint, the eight-gate write path |
| [`interactions.html`](interactions.html) | Seven sequence diagrams: startup handshake, scope and coverage, a refused write, pinning behaviour, a reverted refactoring, the loop reopening, completion and the RACN commit |

Both are read from the source rather than written from memory: `phases.py` for
states and permissions, `simple_design.py` for the rule loop, `service.py` for
the gates, `git_gate.py` and `languages/python.py` for the subprocesses.

Published copies (private):

- State machine — https://claude.ai/artifact/AS4BbPkjaRQvE4Hu2ViRjd
- Interactions — https://claude.ai/artifact/Sop49QdVP84Vhwj3Mq2oX9
