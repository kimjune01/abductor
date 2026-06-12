# Example repair prompt

A ready-to-use prompt that hands the abductor loop to a coding agent (codex, Claude, etc.). It is deliberately **leak-free**: it demands generality and supplies the executable gate, but never names the discriminating property or the fix location — the model has to find the rule itself. Fill the `<…>` slots.

---

You are fixing a real bug in `<project>`. Work only inside `<repo path>`, your current directory.

## The bug

`<one-paragraph statement of the reported failure + a minimal reproducer the tool currently mishandles>`

## What counts as done — a NARROW fix is NOT acceptable

Making the tool handle the reported case is necessary but not sufficient. The report is ONE example. A fix keyed to incidental features of how that example is written — so the reported case is handled but other inputs wrong for the same underlying reason still are not — is over-narrow and will be rejected. Deliver the most general fix that stays correct and does not over-reject:
- generality: every input wrong for the same root reason is now handled;
- no regression: inputs that were already correct still are.

## The gate decides generality — not your own tests

Hand-picked tests only cover what you already suspect. Instead, hill-climb against `abductor`, which holds a calibrated, enumerated space of cases with external ground truth you must not read.

1. Reproduce, then diagnose and fix the ROOT cause.
2. Grade your build:
   ```
   abductor grade --calib <calib.json> --candidate <your build>
   ```
   It returns `pass=false` with the first mishandled cases, or `pass=true` only when every wrong case flips and nothing correct regresses.
3. Each mishandled case is a counterexample outside your current hypothesis. Fix the deeper cause, rebuild, re-grade. Do NOT stop at the first build that handles the reported case — stop only at `pass=true` with zero collateral.
4. Then attack the off-diagonal yourself: construct an input where what the tool *believes* and what is *true* disagree, and a genuinely-valid input that superficially resembles the bug. Confirm the first is handled and the second is not over-rejected.

## Boundaries

- Do not consult git history, branches, or any remote for "the fix" — it is not reachable and looking is cheating.
- Do not read abductor's labels, calibration internals, or held-out probes — that is the answer key.
- Modify only non-test source.

## Report

- VERDICT: does the gate pass? held-out / over-rejection / regression results?
- Files and functions changed; one-paragraph root-cause and fix.
- The `changed`/`mishandled` trajectory across your iterations.

---

The leak-free property is what makes a run *evidence*: if the model reaches the general predicate, it reconstructed it — the gate supplied counterexamples, never the answer.
