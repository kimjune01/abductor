---
name: debug
description: Fix a bug whose correct fix is a general PREDICATE (not a single case) by hill-climbing against an external abductor gate while building a hypothesis graph. The gate forces the model to represent the rule instead of tabulating the example; the graph records why each fix died and what it generated. Use when a repair must generalize — soundness bugs, missing-case checks, taxonomy/classification fixes — and "make it general" prompting plateaus narrow.
---

# debug

You are repairing a bug whose real fix is a property over a whole family of inputs, not just the reported one. Left to itself a model patches the reported case; told to self-test, it tests what it already believes. `abductor` breaks that loop by holding an answer key you cannot see — a calibrated, enumerated space of cases with external ground truth — and you hill-climb against it.

You record the climb as a **hypothesis graph**. Each fix you try is a node; the gate run is its perturbation; the cases it mishandles are the kill condition; the deeper cause they point to is the edge to the next node. The gate is the reward, the graph is the memory. Write it to `abduct-graph.md` and grow it as you go — never truncate it.

## The loop (each pass adds a node)

1. **Reproduce.** Confirm the reported failure on a clean baseline. This is H₀.

2. **Calibrate the gate (once).** Enumerate a fixpoint-closed space of the relevant input formers — wider than your hypothesis — and label each case against the known-good baseline:
   ```
   abductor calibrate --baseline <known-good> --space <property-grammar> -o calib.json
   ```

3. **State a hypothesis, then fix at the root.** Write the node before you build: what you believe the root cause is, and the fix it implies. Resist keying on incidentals of the reported example.

4. **Perturb — grade the build. The gate judges, not you.**
   ```
   abductor grade --calib calib.json --candidate <your-build>
   ```
   `pass=false` returns the first mishandled cases; `pass=true` only when every bug case flips and nothing valid regresses.

5. **Classify the trajectory** of `changed`/`mishandled` across your nodes so far:
   - *convergent* — mishandled shrinking toward zero: keep pushing the same edge.
   - *oscillatory* — flips a different set each pass: the hypothesis is too coarse; split it.
   - *divergent* — a fix that breaks valid cases: wrong direction, back out.
   - *chaotic* — no pattern: the space or the diagnosis is wrong; re-decompose.

6. **Follow the edge.** Each mishandled case is a counterexample outside your current hypothesis — the surprise self-testing never gives you. It is the kill condition; the deeper cause it exposes is the edge. Add the node (hypothesis, gate result, trajectory, the killing cases, the edge), then return to step 3 on that edge.

7. **Widen, then stop.** When the gate passes, interrogate the off-diagonal — the cases where what the tool *believes* and what is *true* disagree (the XOR). If the space didn't cover them, widen it and re-grade. Stop when a genuinely broad gate finds nothing and the graph's frontier is closed.

## The graph document (`abduct-graph.md`)

- **Nodes** — one per fix attempt: hypothesis, the gate result (`pass`, `changed`, `mishandled` sample), trajectory class, kill condition (the cases that killed it), edge (the deeper cause → next hypothesis).
- **Frontier** — open edges not yet tried, with the trajectory you predict.
- **Pruning log** — hypotheses the gate killed and the exact counterexample that did it. Dead nodes are information; keep them.

## Discipline

- **Never read the gate's labels or held-out probes.** Consuming the key turns the climb into tabulation of the key.
- **Pass is necessary, not sufficient.** A fix can pass the enumerated space and still break a held-out shape outside it. Keep a few sealed held-outs for a final, separate check.
- **Don't game the gate.** Crashing, excluding hard cases, or over-rejecting valid ones is not a pass; the gate scores those as failures.
- **The graph composes.** A closed sub-graph (one property, gated and confirmed) is a node in a larger one — reuse it; don't re-derive it.

See `examples/repair-prompt.md` for a ready prompt that hands this loop to a coding agent.
