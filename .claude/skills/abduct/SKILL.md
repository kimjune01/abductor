---
name: abduct
description: Fix a bug whose correct fix is a general PREDICATE (not a single case) by hill-climbing against an external abductor gate, so the model is forced to represent the rule instead of tabulating the example. Use when a repair must generalize — soundness bugs, missing-case checks, taxonomy/classification fixes — and "make it general" prompting plateaus narrow.
---

# abduct

You are repairing a bug whose real fix is a property that holds over a whole family of inputs, not just the reported one. Left to itself a model patches the reported case and stops; told to self-test, it tests what it already believes. `abductor` breaks that loop by holding an answer key you cannot see: a calibrated, enumerated space of cases with external ground truth. You hill-climb against the gate until it passes.

## The loop

1. **Reproduce.** Confirm the reported failure on a clean baseline. Do not fix yet.

2. **Calibrate the gate (once).** Point abductor at the property and the known-good baseline so every enumerated case carries an external label:
   ```
   abductor calibrate --baseline <known-good> --space <property-grammar> -o calib.json
   ```
   The space is a fixpoint-closed enumeration of the relevant input formers — wider than your current hypothesis. Calibration records, per case, what the baseline does and what is correct.

3. **Fix at the root.** Diagnose the underlying cause and change it. Resist keying on incidental features of the reported example.

4. **Grade — the gate judges, not you.**
   ```
   abductor grade --calib calib.json --candidate <your-build>
   ```
   It returns `pass=false` with the first mishandled cases, or `pass=true` only when every bug case flips and no valid case regresses.

5. **Climb.** Each mishandled case is a counterexample outside your current hypothesis — exactly the surprise self-testing never gives you. Return to step 3, fix the deeper cause, rebuild, re-grade. Iterate until `pass=true` with zero collateral.

6. **Widen, then stop.** When the gate passes, check the off-diagonal: the cases where what the tool *believes* and what is *true* disagree (the XOR). If the space didn't cover them, widen it and re-grade. Stop when a genuinely broad gate finds nothing.

## Discipline

- **Never read the gate's labels or the held-out probes.** The gate is an oracle; consuming its key turns the loop into tabulation of the key.
- **Pass is necessary, not sufficient.** A fix can pass the enumerated space and still break a held-out shape outside it (over-general) — keep a few sealed held-outs for a final, separate check.
- **Don't game the gate.** Crashing, excluding hard cases, or over-rejecting valid ones is not a pass; the gate scores those as failures.
- **Report the trajectory.** Log how `changed`/`mishandled` moved across iterations — convergent vs oscillatory tells you whether the predicate is in reach.

See `examples/repair-prompt.md` for a ready prompt that hands this loop to a coding agent.
