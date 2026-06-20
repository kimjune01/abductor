---
name: abduct
description: Fix a bug whose correct fix is a general PREDICATE (not a single case) by hill-climbing against an external abductor gate while building a hypothesis graph. The gate forces the model to represent the rule instead of tabulating the example; the graph records why each fix died and what it generated. Use when a repair must generalize — soundness bugs, missing-case checks, taxonomy/classification fixes — and "make it general" prompting plateaus narrow.
---

# abduct

You are repairing a bug whose real fix is a property over a whole family of inputs, not just the reported one. Left to itself a model patches the reported case; told to self-test, it tests what it already believes. `abductor` breaks that loop by holding an answer key you cannot see — a calibrated, enumerated space of cases with external ground truth — and you hill-climb against it.

You record the climb as a **hypothesis graph**. Each fix you try is a node; the gate run is its perturbation; the cases it mishandles are the kill condition; the deeper cause they point to is the edge to the next node. The gate is the reward, the graph is the memory. Write it to `abduct-graph.md` and grow it as you go — never truncate it.

## The loop (each pass adds a node)

1. **Reproduce.** Confirm the reported failure on a clean baseline. This is H₀.

2. **Build the answer key (once).** Enumerate a fixpoint-closed space of the relevant input formers — wider than your hypothesis — and label each case against the known-good baseline into an **accept-set** (the integers the baseline accepts). This is the gate's hidden truth; the tool grades against it but never shows it to you. The gate consumes accept-sets directly (a file of integers, or an `--sketches` IBLT blob); there is no separate `calibrate` step — you produce the accept-set, the gate reconciles against it.

3. **State a hypothesis, then fix at the root.** Write the node before you build: what you believe the root cause is, and the fix it implies. Resist keying on incidentals of the reported example.

   **Red-team the priors before committing.** Abduction is the un-checkable leap: the gate grades fixes, but nothing grades *which root cause you conjectured*. Before fixing at the root, invoke the **`red-team`** skill on the open hypothesis nodes (§5a branch features included). It fans out adversaries tasked to refute, not confirm — cross-family by default — kills priors that don't survive, and adds alternatives you anchored away from as new open nodes. It does not verify the prior (nothing can); it hardens the conjecture and leaves a replayable adversarial trail. Commit the inquiry to a root-cause direction only after the volley converges.

4. **Perturb — grade the build with `gate`. The gate judges, not you.** Emit your candidate's accept-set and reconcile it against the truth accept-set:
   ```
   abductor gate --believe <(./fix) --truth truth.txt        # exit 0 agree, 10 disagree
   ```
   Exit 0 means every case agrees; exit 10 returns the symmetric difference (`false_positives` = wrongly accepted, `false_negatives` = wrongly dropped) — your counterexamples. Drive the loop with `node probe`, which runs this trial and classifies the node by its exit code in one call (see *The graph document*).

5. **Classify the trajectory** of the disagreement (`false_positives`/`false_negatives`) across your nodes so far:
   - *convergent* — disagreement shrinking toward zero: keep pushing the same edge.
   - *oscillatory* — flips a different set each pass: the hypothesis is too coarse; split it.
   - *divergent* — a fix that breaks valid cases. **Read WHICH cases broke before you back out:**
     - *uniform regression* — the break hits a case-class unrelated to the cases the fix repaired: wrong direction, back out.
     - *token-adjacent flip* — the fix repairs a case and breaks its **surface-twin** (same surface signature, opposite required verdict — the Verus `!` case: a ghost-erased uninhabited return must KEEP its edge, a genuine runtime divergence must PRUNE it). This is **not** a wrong direction; it is a **branch point**. The surface hides two case-classes that demand opposite verdicts, and backing out discards exactly the signal that says *split here*. Do not back out — run the diff-the-diff check (step 5a) and split.
   - *chaotic* — no pattern: the space or the diagnosis is wrong; re-decompose.

5a. **Diff-the-diff routing (the branch-point check).** When step 5 flags a *token-adjacent flip*, conjecture the hidden branch feature that separates the twins and build two oracles from it: a **base** (the foil — what the surface alone would accept) and a **reference** (the truth — what the feature-aware spec accepts). **Red-team the conjectured branch FEATURE before running the gate** — invoke `red-team` on the branch node. The gate cannot catch a mis-conjectured feature; it can only check a candidate against whatever split you supply, so a wrong branch point makes the whole second-order check answer the wrong question. The framing challenger asks "is THIS the feature that splits the token-identical cases, or is it something else?" and names rival features. Only once the feature survives the volley, build the two oracles and run the directional, second-order set-difference check (the verification analogue of OSL tri-abduction, Zilberstein, Saliling & Silva 2024, arXiv:2305.04842 — the tool only *checks*; you conjecture the branch and supply both oracles):
   ```
   abductor gate --believe <(./fix) --truth <base-oracle> --reference <reference-oracle>
   ```
   The verdict is the exit code, and **a collapse is NON-TERMINAL** — it is a re-entry, never a "done". The directional kill-edge names the next hypothesis; route on it:

   | exit | verdict | what it means | kill-edge → next hypothesis |
   | --- | --- | --- | --- |
   | 0 | `pass` | matches the reference (truth) on both axes | witnessed — the split holds |
   | 11 | `collapse_wide` | sided with the base on the over-wide axis (keeps cases the reference rejects) | **narrow the predicate** — re-enter |
   | 12 | `collapse_narrow` | sided with the base on the over-narrow axis (drops cases the reference keeps) | **widen the predicate** — re-enter |
   | 13 | `collapse_both` | collapsed on both axes at once | **wrong both directions** — re-condition the feature, re-enter |
   | 10 | `disagree` | wrong where the two oracles AGREE (the core, off both axes) | not a branch issue — the fix is wrong on the agreement set; re-enter |

   Only exit 0 closes the branch. Each collapse code names the axis you dropped and the offending case-IDs (`over_wide`/`over_narrow`/`core_errors` in the JSON); condition the fix on the feature in the direction the kill-edge names and re-run until exit 0. A collapse must never resolve the loop — `node probe` records it as a `collapsed` (non-terminal) node that links to its successor.

6. **Follow the edge.** Each disagreeing case is a counterexample outside your current hypothesis — the surprise self-testing never gives you. It is the kill condition; the deeper cause it exposes is the edge. Add the node (hypothesis, gate result, trajectory, the killing cases, the edge), then return to step 3 on that edge.

7. **Widen, then stop.** When the gate passes, interrogate the off-diagonal — the cases where what the tool *believes* and what is *true* disagree (the XOR). If the space didn't cover them, widen it and re-grade. Stop when a genuinely broad gate finds nothing and the graph's frontier is closed.

## The graph document (`abduct-graph.md`)

One markdown graph file per inquiry. Drive it with `node probe`: it runs the trial, classifies the node by the exit code, and writes the `.md` audit copy on every step, so the record is replayable rather than a trust-me log.

- **Nodes** — one per fix attempt: hypothesis, the gate result (the verdict and disagreeing-case sample), trajectory class, kill condition (the cases that killed it), edge (the deeper cause → next hypothesis).
- **Branch nodes (emit every diff-the-diff check as one).** When you run the step-5a check, record it as a node via `node probe` so the branch-composition reasoning is **verifiable knowledge, not a trust-me log**. The node captures the exact replayable trial (the `gate --reference` command), the directional verdict (`pass`/`collapse_wide`/`collapse_narrow`/`collapse_both`/`disagree`) as a first-class field, the per-axis offending case-IDs (`over_wide`/`over_narrow`/`core`), and a credence. A collapse is recorded as a `collapsed` (non-terminal) node and links its successor via `--from`. The replay invariant holds: a stranger re-runs the recorded `gate --reference` command and gets the same collapse exit, reconstructing the verdict without trusting you.
  ```
  abductor node probe "fix conditioned on <branch feature>" \
      --trial "abductor gate --believe <(./fix) --truth base.txt --reference ref.txt"
  # exit 11 → node recorded collapsed, verdict=collapse_wide, axes over_wide=[…]
  abductor node probe "narrow the predicate on <feature>" --from <collapsed-id> \
      --trial "abductor gate --believe <(./fix2) --truth base.txt --reference ref.txt"
  ```
- **Frontier** — open edges not yet tried, with the trajectory you predict.
- **Pruning log** — hypotheses the gate killed and the exact counterexample that did it. Dead nodes are information; keep them.

## Discipline

- **Never read the gate's labels or held-out probes.** Consuming the key turns the climb into tabulation of the key.
- **Pass is necessary, not sufficient.** A fix can pass the enumerated space and still break a held-out shape outside it. Keep a few sealed held-outs for a final, separate check.
- **Don't game the gate.** Crashing, excluding hard cases, or over-rejecting valid ones is not a pass; the gate scores those as failures.
- **The graph composes.** A closed sub-graph (one property, gated and confirmed) is a node in a larger one — reuse it; don't re-derive it.

See `examples/repair-prompt.md` for a ready prompt that hands this loop to a coding agent.
