# Toy: a branch-structured validator for diff-the-diff

A minimal toy with genuine **branch** structure — two oracles that demand opposite
verdicts on a hidden sub-class, so a naive fix is *wide-but-broken* (right on the
agreement core, silently wrong on one axis of the divergence). It exercises
**diff-the-diff**, `abductor gate --believe C --truth BASE --reference REF` — a
directional, second-order symmetric-difference *check* (the checking analogue of
tri-abductive synthesis, OSL §5.1; it does not perform the anti-frame inference).
The single-oracle `leap_year` toy cannot
reach it: leap_year has one truth, so it can disagree (exit 10) but never *collapse
a branch* (exit 11/12/13).

In diff-the-diff the **reference is truth** and the **base is the foil**. The spec's
own diff is kept directional (`W`/`N` below are diff-the-diff's own axis sets, an
informal analogy to — not — OSL's leftover frames):

- `W = BASE \ REF` — the **over-wide axis** (base accepts, reference rejects).
- `N = REF \ BASE` — the **over-narrow axis** (reference accepts, base rejects).

The candidate's error against truth, `Δ = C △ REF`, is decomposed over
`{core, W, N}`. Riding W is `collapse_wide` (11), N is `collapse_narrow` (12),
both is `collapse_both` (13); an error on the core (where the oracles agree) is a
plain `disagree` (10); `Δ` empty is `pass` (0).

## Part 1 — a wide-only divergence (`base.txt` / `reference.txt`)

A validator over small integers `1..20`. The accept-sets list the accepted integers;
anything absent is rejected.

| oracle | rule | accepts |
| --- | --- | --- |
| **base** (`base.txt`) — the buggy baseline (foil) | `even` | `2 4 6 8 10 12 14 16 18 20` |
| **reference** (`reference.txt`) — the approved fix (truth) | `even ∧ not a perfect square` | `2 6 8 10 12 14 18 20` |

Here `REF ⊂ BASE`, so the divergence is one-sided: `W = {4, 16}` (the even perfect
squares the base wrongly keeps), `N = ∅`. The hidden branch feature is
perfect-square-ness — on the surface `4` and `16` look like any other even number,
but under the feature they demand the *opposite* verdict. This is the clean analog
of the Verus `!` case in `docs/CLI.md`.

| candidate | accepts | Δ vs reference | verdict | exit |
| --- | --- | --- | --- | --- |
| `cand_correct.txt` | `even ∧ ¬square` (= reference) | ∅ | `pass` | 0 |
| `cand_wide.txt` | `even` (= base) | `{4,16}` ⊆ W | `collapse_wide` | 11 |
| `cand_bad.txt` | `1 3 5 7 9` (odds) | hits the core | `disagree` | 10 |

```bash
# (a) PASS (exit 0): candidate matches the reference (truth).
abductor gate --believe cand_correct.txt --truth base.txt --reference reference.txt

# (b) COLLAPSE_WIDE (exit 11): the wide-but-broken fix keeps {4,16} the reference drops.
abductor gate --believe cand_wide.txt --truth base.txt --reference reference.txt
#   -> over_wide [4, 16]

# (c) DISAGREE (exit 10): odds are wrong on the agreement core, not on either axis.
abductor gate --believe cand_bad.txt --truth base.txt --reference reference.txt
```

`cand_wide.txt` is the **wide-but-broken** fix: it satisfies the buggy baseline
perfectly while silently keeping the two squares the approved fix removes. A
bi-abductive gate against the base alone would bless it; diff-the-diff catches it and
*names the axis it collapsed onto* (`over_wide`).

## Part 2 — a both-directions divergence (`bd_*.txt`)

The wide-only toy has `N = ∅`, so it can never reach `collapse_narrow` or
`collapse_both`. The `bd_*` files add a divergence where **each oracle accepts
something the other rejects**, exercising the full matrix.

| oracle | accepts |
| --- | --- |
| **base** (`bd_base.txt`) — foil | `2 4 6 10 14 16 18` |
| **reference** (`bd_reference.txt`) — truth | `2 3 6 9 10 14 18` |

The directional spec diff: `W = BASE \ REF = {4, 16}` (over-wide axis),
`N = REF \ BASE = {3, 9}` (over-narrow axis); the agreement core is
`{2, 6, 10, 14, 18}`.

The five candidates and their verdicts:

| candidate | accepts | Δ vs reference | verdict | exit |
| --- | --- | --- | --- | --- |
| `bd_pass.txt` | `2 3 6 9 10 14 18` (= reference) | ∅ | `pass` | 0 |
| `bd_wide.txt` | reference `+ 4` | `{4}` ⊆ W | `collapse_wide` | 11 |
| `bd_narrow.txt` | reference `− 3` | `{3}` ⊆ N | `collapse_narrow` | 12 |
| `bd_both.txt` | reference `+ 4 − 3` | `{4}`∈W, `{3}`∈N | `collapse_both` | 13 |
| `bd_disagree.txt` | reference `− 2` | `{2}` on the core | `disagree` | 10 |

```bash
abductor gate --believe bd_pass.txt     --truth bd_base.txt --reference bd_reference.txt  # exit 0
abductor gate --believe bd_wide.txt     --truth bd_base.txt --reference bd_reference.txt  # exit 11  over_wide   [4]
abductor gate --believe bd_narrow.txt   --truth bd_base.txt --reference bd_reference.txt  # exit 12  over_narrow [3]
abductor gate --believe bd_both.txt     --truth bd_base.txt --reference bd_reference.txt  # exit 13  over_wide [4], over_narrow [3]
abductor gate --believe bd_disagree.txt --truth bd_base.txt --reference bd_reference.txt  # exit 10  core_errors [2]
```

Run each from this directory (`abductor` = `uv run abductor` if not installed); see
`abductor codes` for the verdict table. The JSON also carries a `provenance` block
(exact argv + sha256 of every input) so the verdict is auditable from the artifact
alone, and `spec_diff` (`over_wide_axis`, `over_narrow_axis`) so a reader sees the
divergence the candidate was scored against.

## Why `pass` now means matching truth

`pass` is simply `Δ = C △ REF = ∅` — the candidate equals the reference (truth). It
is reachable whether or not the oracles diverge: unlike an undirected
symmetric-difference check, diff-the-diff does not require base and reference to coincide. Collapsing onto
the base (keeping its over-wide cases or dropping its over-narrow ones) is what earns
a directional collapse code instead; erring where the two oracles agree is a plain
disagreement.
