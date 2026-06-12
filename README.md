# 🛸 abductor

<p align="center"><strong><em>Take me to your invariant.</em></strong></p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0-blue?style=for-the-badge" alt="License: AGPL-3.0"></a>
  <img src="https://img.shields.io/badge/python-3.11+-blue?style=for-the-badge" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/status-experimental-orange?style=for-the-badge" alt="Status: experimental">
</p>

**abductor** externalizes the test so an LLM has to *represent* the rule — not *tabulate* the example.

Hand a model a bug whose real fix is a *predicate* and it patches the case in front of it. Tell it to "be general" and it agrees and stays narrow. Tell it to "write its own tests" and it writes the tests it already believes in. The loop closes on a comfortable, wrong, narrow fix. abductor breaks the loop by holding the answer key the model can't see.

## How it works

1. **Enumerate.** Generate a broad, fixpoint-closed space of cases for the property under repair — wider than the model's hypothesis.
2. **Calibrate.** Grade every case against a known-good baseline, so each carries *external* ground truth.
3. **Gate.** Expose one pass/fail signal. The model hill-climbs against it.

Each gate run is a perturbation; each mishandled case is a kill condition that generates the next hypothesis. The loop records itself as a **hypothesis graph** — fixes are nodes, counterexamples are edges — so the climb is legible and composable. Because the gate's coverage — not the model's prior — sets the frontier, the model is dragged past the example into the rule. In a case study on a real soundness bug, a gate of this shape took a strong model from a narrow one-case patch to a general fix that reached for the verifier's own decision procedure, where six prompt-only "reasoning method" arms stayed narrow.

The thing the gate is really checking is a disagreement — an XOR, a symmetric difference: where *what the compiler believes* and *what is actually true* come apart. That's the check tests and type systems can't give you, because **absence has no test**.

## Install

Zero dependencies, Python 3.11+. Pick one:

```bash
uv tool install git+https://github.com/kimjune01/abductor   # installs the `abductor` command
uvx --from git+https://github.com/kimjune01/abductor abductor --help   # run once, no install
```

From a clone (for development): `uv run abductor --help`. Wherever the PATH shim
is unavailable, `python -m abductor ...` is an exact equivalent — handy for agents.

## Quickstart

```bash
abductor gate --believe candidate.txt --truth baseline.txt   # rc 0 agree, rc 10 disagree
abductor codes                                               # the exit-code verdict table
```

The CLI is **agent-first**: the exit code is the verdict (route on it, no parsing),
JSON goes to stdout when piped, and the tool only caches and reconciles — it never
proposes or ranks a fix. One fused call drives a debug loop:

```bash
abductor graph init "1900 is reported leap, but it is not"
abductor node probe "div by 4" --trial "abductor gate --believe <(./fix) --truth t.txt" --kill-if any
# rc 10 → the node is killed and recorded; read the disagreement, form the next hypothesis
abductor node probe "div by 4, except centuries unless div by 400" --from 0 \
    --trial "abductor gate --believe <(./fix2) --truth t.txt" --kill-if any   # rc 0 → witnessed
abductor replay 1   # re-runs the recorded trial, checks the exact exit code reproduces
```

Every step writes the record: `inquiry.json` (the replay substrate) and a
human-inspectable `inquiry.md` beside it (the audit surface), each node carrying the
exact command a stranger reruns to check it. Keep or commit the pair for the record.

`abductor --help` prints this loop and `abductor codes` the verdict table, so an
agent can drive the tool without leaving the terminal. Design and the full command
surface are in [`docs/CLI.md`](docs/CLI.md). A worked toy (leap-year repair,
hypothesis-graph CRUD, set reconciliation) is in [`examples/leap_year/`](examples/leap_year/).

## Drive it with an agent

abductor ships with the loop that uses it:

- **Skill** — [`/debug`](.claude/skills/debug/SKILL.md): orchestrates reproduce → calibrate → fix → grade → climb while building a hypothesis graph, with the no-peeking discipline.
- **Example prompt** — [`examples/repair-prompt.md`](examples/repair-prompt.md): a leak-free, fill-in-the-blanks prompt that hands the loop to a coding agent (codex, Claude, …). It demands generality and supplies the gate, but never names the property or the fix — so reaching the rule is the model's own reconstruction, not a leak.

## Status

Early and experimental. Born as the `case-check` tool in a verifier case study; this is its clean-room home. The repair-loop API and the first language backends are landing here.

## Background

The reasoning lineage — Peircean abduction, bi-/tri-abduction, incorrectness logic, CEGAR, set reconciliation, the e-value view of evidence — and full citations live in [`docs/LINEAGE.md`](docs/LINEAGE.md).

## License

Copyright © 2026 June Kim. [AGPL-3.0](LICENSE). As sole copyright holder the author reserves the right to dual-license; outside contributions are accepted only under a CLA that preserves this.
