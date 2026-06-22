# diff-the-diff: design note for the sketched pieces

Scratch design (NOT committed). The two-oracle **diff-the-diff gate** is built and
tested (`abductor gate --believe C --truth BASE --reference REF`). This note sketches
the three pieces deliberately left unbuilt, so a human can review the direction
before any of them lands.

The gate is the verification *analogue* of tri-abductive synthesis (Outcome
Separation Logic, Zilberstein–Saliling–Silva 2024 §5.1; `docs/LINEAGE.md:13`) — it
borrows OSL's two-distinct-leftover directional structure but synthesizes nothing,
and the accept-set/heap correspondence is informal. Operationalized here: hold the
surface fixed, flip a hidden branch feature the *model* conjectures, and require the
candidate to give the correct verdict on both oracles. The tool only checks; it
never discovers the branch point. It diffs the spec (BASE vs REF, kept directional),
then classifies where the candidate's own error `Δ = C △ REF` lands against that
directional partition — over-wide axis, over-narrow axis, both, or the agreement
core. There is no lattice op and no join; the verdict is a classification of `Δ`.
The pieces below feed the gate its two oracles and record the result.

---

## 1. Counterfactual PAIR generation at a conjectured branch feature

**Today.** `Gate` (`examples/leap_year/property.py`) enumerates one case space
(`self.cases`) and grades every case against one baseline (`self._truth`). One
space, one oracle, one XOR — single-oracle.

**The gap.** diff-the-diff needs *two* oracles whose verdicts may differ at a
case that looks identical on the surface. The model supplies the **branch feature**
(a predicate over the enumerated space); the tool partitions the space by it and
pairs surface-matched cases across the partition, building one oracle per branch.

**Sketch — where it hooks in.** A calibration helper that takes the existing space
plus a model-supplied `feature` predicate and emits two calibrated accept-sets and
the surface-matched pairing:

```python
# property.py (or a future `abductor calibrate --space ... --branch <feature>`)
@dataclass
class BranchPairs:
    base_truth: set[int]       # answer key on the base branch
    ref_truth: set[int]        # answer key on the reference branch (feature flipped)
    pairs: list[tuple[int, int]]   # (base_case, ref_case): same surface, flipped feature

def calibrate_branches(
    cases: list[int],
    surface: Callable[[int], object],     # surface signature the branch must NOT change
    feature: Callable[[int], bool],       # the MODEL's conjectured branch feature
    truth_base: Callable[[int], bool],    # answer key when feature is off
    truth_ref: Callable[[int], bool],     # answer key when feature is on
) -> BranchPairs:
    by_surface: dict[object, dict[bool, int]] = defaultdict(dict)
    for c in cases:
        by_surface[surface(c)][feature(c)] = c
    pairs = [(s[False], s[True]) for s in by_surface.values() if False in s and True in s]
    base_truth = {b for b, _ in pairs if truth_base(b)}
    ref_truth  = {r for _, r in pairs if truth_ref(r)}
    return BranchPairs(base_truth, ref_truth, pairs)
```

The two accept-sets serialize to the `--truth` / `--reference` files the gate
already consumes. Only surface-matched pairs survive, so the gate is scored on
exactly the counterfactual: same surface, opposite branch.

**Hook into `calibrate`.** There is no `abductor calibrate` subcommand today — the
CLI grades via `gate` over pre-computed int sets, and `SKILL.md` names
`calibrate`/`grade` at the loop level (a known doc/CLI gap, see §3). When a
`calibrate` subcommand lands, `--branch <feature-expr>` is the natural switch from
emitting one `calib.json` to emitting the `(base, reference)` pair. The model writes
the `feature` predicate; the tool does the partition and the two labelings.

**Boundary note.** The IBLT path already reconciles per branch; pair generation is
purely upstream of it, so the `--sketches` path needs no change here.

---

## 2. A hygraph BRANCH NODE

**Today.** A `Node` (`hygraph.py:74`) records one `outcome` (string) and one
`expected_exit` — a single verdict. A directional collapse carries more structure
(which axis the candidate rode, and the per-axis case IDs) that a single `outcome`
field flattens and loses.

**Sketch — extend the node, don't fork it.** Add an optional per-axis record that
is `None` for ordinary single-oracle nodes (so nothing existing changes):

```python
@dataclass
class AxisOutcome:
    axis: str              # "over_wide" | "over_narrow"
    cases: list[int]       # the case IDs the candidate got wrong on this axis

@dataclass
class Node:
    ...
    expected_exit: int | None = None
    axes: list[AxisOutcome] | None = None   # set only for a diff-the-diff probe
    verdict: str | None = None   # "pass" | "collapse_wide" | "collapse_narrow" | "collapse_both" | "disagree"
```

`to_dict`/`from_dict` gain a passthrough for `axes`/`verdict` (both default `None`,
backward-compatible with every saved graph). `to_markdown` renders, under a
collapse node, the per-axis table and which axis was collapsed — the audit surface
shows *why* a wide-but-broken fix died, not just that it did. A diff-the-diff
`node probe` would map exit `11` to a killed node whose `verdict = "collapse_wide"`
and whose `axes` carries the offending case IDs straight from the gate's JSON.

This keeps the single-`outcome` node as the common case and layers the directional
structure on top, the same way `expected_exit` was layered on for `probe`/`replay`.

---

## 3. The `SKILL.md` divergent-trajectory fix

**Today** (`.claude/skills/abduct/SKILL.md:32`):

```
- *divergent* — a fix that breaks valid cases: wrong direction, back out.
```

**The bug.** This routes *every* break of valid cases as a failed direction to back
out of. But a fix that breaks valid cases **on one branch while fixing them on
another, token-adjacent** case is not a wrong direction — it is a **branch signal**:
the surface hides two cases that need opposite verdicts (the Verus `!` example —
ghost-erased uninhabited return must KEEP its edge; a genuine runtime divergence
must PRUNE it). Backing out discards exactly the information that says "split here."

**Sketch — replacement step.** Distinguish a uniform regression from a directional
collapse, and route the collapse into the diff-the-diff gate instead of backing out:

```
- *divergent* — a fix that breaks valid cases. Read WHICH cases broke:
  - uniform regression (breaks a class unrelated to the cases it fixed):
    wrong direction — back out.
  - token-adjacent flip (fixes a case and breaks its surface-twin — same surface,
    opposite required verdict): a BRANCH POINT, not a failed direction. Conjecture
    the hidden branch feature that separates the twins, split the oracle by it, and
    re-grade with the diff-the-diff gate:
        abductor gate --believe <fix> --truth <base-branch> --reference <ref-branch>
    Exit 11/12/13 (collapse_wide/narrow/both) names the axis you dropped; condition
    the fix on the feature and re-run until exit 0 (agrees with the reference).
```

The trajectory vocabulary stays the same; *divergent* simply forks on whether the
break is uniform (back out) or token-adjacent (split and re-grade). This is the only
edit that turns a discarded signal into the entry point for the branch-structured
check.
</content>
</invoke>
