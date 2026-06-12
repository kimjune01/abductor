# The abductor CLI — design

The caller is an **agent in a debug loop**, not a human at a prompt. So the
design starts from [clig.dev](https://clig.dev/) — the written-down conventions
of the command line ([Platform Conventions](https://june.kim/platform-conventions)
catalogs it as "the Butterick of CLIs") — and bends each one toward the agent.
clig.dev is inspirational, not gospel.

## Two load-bearing principles

### 1. The tool holds a cache; the agent holds the judgment

The division of intellect has to be obvious from the command list. abductor is an
**efficient cache with algorithmic operations, never judgment**:

| The tool does (algorithmic, deterministic) | The agent does (judgment) |
| --- | --- |
| reconcile two sketches → the disagreement (`gate`) | propose the hypothesis (abduction) |
| encode a set into an O(d) sketch (`sketch`) | write the trial command |
| append / classify / link / prune a node (`node …`) | read the counterexamples, decide what they mean |
| replay a recorded command and diff the verdict (`replay`) | form the next hypothesis from the manner of death |
| store and render the graph (`graph …`) | decide when the inquiry is done |

There is, on purpose, no `abductor diagnose` and no `abductor suggest`. The line is
about **content judgment**, drawn precisely: the tool applies fixed mechanical
predicates (set difference, is-it-empty, did-the-exit-code-match) but never
proposes a hypothesis, ranks a fix, or interprets what a counterexample means. Its
vocabulary is judgment-shaped — `kill`, `witness`, `credence` — but the agent
supplies all the content under those labels; the tool only files and checks it.
Every output is a mechanical function of its input, which is exactly why the agent
can trust it. This is the [division of intellect, not labor](https://june.kim): the
tool is clever (the IBLT sketch, the append-only store); the agent is intelligent
(the abduction).

One honest boundary: the graph commands record the agent's classifications without
re-running the trial, so the graph is a **journal** by default. `node probe` (and
`replay`) close that gap — they run the trial themselves and classify by its exit
code — turning the relevant nodes into a **verified ledger** a stranger replays.

### Preserve the graph, regenerate the diffs

The only artifact the tool preserves is the hypothesis graph: hypotheses, trial
commands, verdicts, the edges between them. It deliberately does **not** store the
candidate diffs or the trial's output (the disagreement / counterexamples), because
those are *regenerable* — re-running the recorded trial reproduces them. So
`node probe` and `replay` **pass the trial's stdout through** to the agent (in a
transient `trial_stdout` field it reads to form the next hypothesis) while the node
itself keeps only a one-line mechanical `outcome` (`trial exit 10`). The graph is
the durable record; the diff is a re-derivable shadow of it. This is what keeps the
tool a lean cache instead of an archive: it holds the reasoning skeleton and trusts
replay to rebuild everything hanging off it.

### The cache lives in memory

Because only the skeleton is kept, the cache is tiny: a complete three-node
inquiry serializes to ~700 bytes, and a 100-node deep one is ~25 KB. So the graph
is just an in-memory structure — there is no database, no index, nothing to query
over a wire. The library form (`HypothesisGraph` in `abductor.hygraph`) *is* the
cache: build it, mutate it, and the whole inquiry lives in one process's RAM, never
touching disk (`examples/leap_year/inquiry.py` runs exactly this way). The IBLT
sketch is likewise O(d) and in-memory.

The CLI's `--graph FILE` is therefore a small JSON dump of that in-memory
structure, written so a fresh `abductor` process (a new shell, a separate agent
step) can pick the inquiry back up. If the harness is a single long-lived process,
skip the file and hold the `HypothesisGraph` in memory directly.

### Saved for the record, and built to be audited

That same file is the durable record — and auditability is the point, so it is
written to be inspected, not just resumed. Every `save` writes two siblings: the
`.json` is the replay substrate a fresh process loads; a `.md` beside it is the
**human-inspectable audit surface**, regenerated on every step so it is never
stale. An auditor opens `inquiry.md` and reads the whole inquiry — each hypothesis,
its exact trial command, its verdict, its credence, and the exit code at which it
`reproduces` — without running anything. Nothing is hidden behind a query: it is a
flat, append-only text file. The agent "saves for the record" simply by keeping (or
committing) the pair; the warrant travels with it, because every node names the
exact command a stranger reruns to check it. `abductor graph show --markdown` prints
the same surface on demand.

### 2. The exit code is the verdict

clig.dev: "return zero on success, non-zero on failure." Pushed to its agent
conclusion, the exit code *is* the methodeutic gate — the agent routes its loop on
the status code with no parsing and no model in the decision:

| code | meaning |
| --- | --- |
| `0`  | success / **agreement** — a hypothesis witnessed |
| `1`  | unexpected error |
| `2`  | usage error (argparse) |
| `3`  | graph or node not found |
| `4`  | sketch too small to decode, or a replay did not reproduce |
| `10` | **disagreement found** — a hypothesis killed |

`gate` returns `0` or `10`; that single bit drives `node witness` vs `node kill`,
and `node probe` does both in one call. The table is itself machine-readable at
`abductor codes --json`, so an agent never scrapes these docs to learn the verdicts.

## The output contract (clig.dev, adapted)

- **stdout is the artifact; stderr is narration.** Straight from clig.dev. Data an
  agent consumes (the disagreement, a node, the graph) goes to stdout; progress and
  errors go to stderr prefixed `abductor:`.
- **JSON by default for machines.** clig.dev says human-readable by default and
  `--json` for machines, detecting a TTY. We keep the detection but flip the
  default consumer: when stdout is **not** a TTY (an agent, a pipe), output is
  compact single-line JSON automatically — one object per line, cheap to parse and
  to tokenize. `--pretty` indents it; `--human` forces a table; `--json` forces
  JSON. All of these work before *or* after the subcommand (`abductor --json gate …`
  and `abductor gate … --json` are equivalent).
- **Never prompt.** clig.dev: "never require a prompt." For an agent it is absolute
  — no command blocks on input. Destructive acts take an explicit flag (`graph
  init --force`) and fail closed to stderr rather than asking.
- **Deterministic and replayable.** Same inputs → same stdout and same exit code.
  `replay` re-runs a node's recorded command and checks the verdict reproduces,
  which is the hypothesis graph's soundness invariant made executable.
- **verb-noun, composable.** `gate`, `sketch`, `graph show`, `node add`. Reads
  from files or `-` (stdin); the graph file is configurable via `--graph` or
  `ABDUCTOR_GRAPH`. Pieces compose; nothing is monolithic.

## Why a sketch and not an XOR

The gate computes a symmetric difference between *what the candidate believes* and
*what is true*. The naive `a ^ b` is what we cannot afford **at a boundary**:
in-context the agent would read both full accept-sets into its window to find the
few that disagree. `gate` and `sketch` adopt **set reconciliation** (Eppstein et
al. 2011; `docs/LINEAGE.md`): the disagreement is recovered from an O(d) sketch.

Be precise about where the win lands. Plain `abductor gate` on two local set files
still reads both sets — it is an O(n) local convenience, and for small loops a
sorted diff would do. The asymptotic payoff is **`--sketches`**: each party encodes
its set once into an O(d) blob (`abductor sketch`), and two parties — two agents,
two runs, a remote baseline — reconcile from those blobs alone, the full sets never
meeting and never entering a context window. That is the regime the structure is
for; on one local machine it is mostly future-proofing.

## Command surface

```
abductor gate     --believe SET --truth SET [--sketches] [--cells N]   # reconcile → verdict
abductor sketch   SET --cells N [--k 4] [--out FILE]                    # encode an O(d) sketch
abductor graph    init OBSERVATION [--force] | show [--markdown]        # the smem the tool owns
abductor node     probe HYP --trial CMD [--kill-if COND] [--from PARENT] # create + test + classify
                  add   HYP --trial CMD --kill-if COND [--from PARENT]  # create / link (journal)
                  kill  ID --outcome TEXT                               # update (refuted)
                  witness ID --outcome TEXT [--credence F]              # update (test-backed)
                  prune ID                                              # delete from frontier
abductor replay   ID                                                    # re-run trial, check exact exit
abductor codes                                                         # the exit-code verdict table
```

The recommended loop uses `node probe`, which fuses create → run-trial → classify
into one call (the verdict is the trial's exit code, and that code is recorded so
`replay` can check exact reproduction):

```bash
abductor graph init "year 1900 reported leap, but it is not"
abductor node probe "special-case 1900" \
    --trial "abductor gate --believe <(./fix) --truth truth.txt"    # rc 10 -> killed
# read the disagreement from probe's trial_stdout, form the next hypothesis from how it died
abductor node probe "div by 4, skip centuries unless div by 400" --from 0 \
    --trial "abductor gate --believe <(./fix2) --truth truth.txt"   # rc 0 -> witnessed
abductor replay 1     # re-runs the trial; reproduces iff the exit code matches exactly
```

Trials run under `/bin/bash`, so process substitution `<(...)` works. The
finer-grained `node add` + `node kill`/`witness` path stays available when the
agent wants to record a classification it reached some other way (a journal, not a
replayable ledger). Either way the agent supplies every hypothesis and reads every
result; the tool reconciles, records, and replays — and never decides what any of
it means.
