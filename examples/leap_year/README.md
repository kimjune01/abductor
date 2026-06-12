# Toy: leap-year repair as a hypothesis-graph inquiry

A self-contained example of the two structures `abductor` is built around:

1. **The hypothesis graph** (`hygraph.py`) — a typed, append-only semantic memory
   for a debugging agent, with CRUD-like convenience methods.
2. **Set reconciliation** (`iblt.py`) — the parts-bin algorithm that computes the
   gate's disagreement (the XOR) without materializing both sets.

## The problem

The real fix for a leap-year predicate is a *rule*, not a case patch. The shipped
bug is `year % 4 == 0`. A bug report says "1900 is reported leap but isn't." An
agent that patches the case in front of it stays narrow; the gate has to drag it
to the rule. `property.py` holds the answer key (the calibrated baseline) the
agent can't see and exposes only the disagreement.

## Why not just XOR the accept-sets?

The gate checks a symmetric difference: cases where *what the candidate believes*
and *what is true* come apart. Computing that by materializing both accept-sets
and diffing them is what we can't afford —

- **in-context** the agent would read both full sets (~600 leap years each over
  1..2400) into its window to find the handful that disagree;
- **in-CPU** it's an O(|A| + |B|) enumerate-and-diff every probe.

`iblt.py` adopts set reconciliation (Eppstein, Goodrich, Uyeda & Varghese,
*What's the Difference?*, SIGCOMM 2011; see `docs/LINEAGE.md`). Each set is
encoded into an IBLT **sketch** sized to the expected *difference* d, not the set
size. Subtract the two sketches, "peel" the result, and recover the difference in
O(d). In a real deployment only the O(d) sketch crosses the boundary — into a
context window, over a wire, or between two agents — never the full sets.

## The CRUD operations

`hygraph.py` exposes the operations from *The Hypothesis Graph* (june.kim):

| op       | method                       | meaning                                            |
| -------- | ---------------------------- | -------------------------------------------------- |
| create   | `abduce()`                   | append a hypothesis with its kill condition + trial |
| read     | `frontier()`, `replay()`     | query open nodes; reconstruct a node from its trial |
| update   | `kill()`, `witness()`        | classify by outcome (write-once verdict)            |
| link     | `from_kill()`                | a dead hypothesis names its successor               |
| delete   | `prune()`                    | drop a dead branch; the record stays replayable     |

The agent-facing convenience is `probe()`: one call runs abduce → test → classify
against the gate and hands back the counterexamples, so the next hypothesis
answers the manner of the last one's death.

**Soundness invariant.** Every node is reconstructible from its recorded trial by
someone who doesn't trust the author. `replay()` enforces it literally: it reruns
the stored trial and checks the result against what the node recorded.

## Run it

```bash
cd examples/leap_year
uv run python inquiry.py      # the climb: special-case -> centuries -> the rule
uv run python test_loop.py    # 11 checks (IBLT + gate + CRUD)
```

The inquiry kills two narrow fixes and witnesses the rule, each kill naming the
next node, and replays every node on a fresh gate to confirm the invariant.

`inquiry.py` drives the library in-process. The same loop is available to an agent
over the CLI (`abductor gate`, `abductor node …`, `abductor replay`), where the
exit code is the verdict — see [`docs/CLI.md`](../../docs/CLI.md).
