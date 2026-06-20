---
name: red-team
description: Volley-style adversarial challenge of the OPEN hypotheses (the priors) in a hypothesis-graph file. Abduction is the un-checkable leap — no oracle verifies "is this the right root cause" — so you cannot VERIFY a prior, but you can RED-TEAM it: fan out adversaries tasked to REFUTE (not confirm), surface alternatives a single conjecturer anchors away from, and loop to convergence. Cross-family by default (a different model family catches what the generator's own distribution can't). Records survivors, kills, and surfaced alternatives back into the graph as a replayable adversarial trail. Use before committing an inquiry to a root cause, and on a diff-the-diff branch feature before running the gate.
---

# red-team

Abduction — conjecturing the root-cause hypotheses (the priors) — is the un-checkable
leap. There is no oracle for "is this the right hypothesis." A single model enumerates
a few causes from its own distribution and anchors on them; told to self-check, it
checks what it already believes. You **cannot verify a prior.** You **can red-team it**:
apply adversarial pressure the way a separate reviewer catches what a self-grading
author ships.

Be honest about what this buys. Red-teaming does **not** make abduction checkable. It
stress-tests the conjecture and surfaces alternatives the generator missed. A survived
prior is a *stronger* prior, never a *verified* one. The only verifiable thing it leaves
behind is the **trail**: which adversary challenged which hypothesis, what refutation
killed it, what alternative walked out of the frame. The graph (the smem) is the
interface — this skill reads the open hypotheses, challenges them, and writes the
results back. It is general: it operates on any graph's open nodes and is invoked *by*
other skills (e.g. `abduct`), not fused into them.

## Input

The **open hypothesis nodes** of the current graph file — the priors under test.

```bash
abductor graph show --markdown --graph "$GRAPH"   # read the inquiry + open nodes
```

The open (status `open`) nodes are the targets. Each carries a `hypothesis` (the
conjectured cause) and, for a diff-the-diff branch node, a conjectured branch `feature`.
Collect them; these are what the volley attacks.

## When to red-team (the guard)

Red-teaming every prior on every loop is expensive (a fan-out of agents, one of them a
cross-family call). Spend it where a wrong prior is costly, not on bookkeeping:

- **Do** red-team before *committing* an inquiry to a root-cause direction — the moment
  in `abduct` where hypotheses are first proposed, before fixing at the root.
- **Do** red-team a **diff-the-diff branch feature** before running the gate. A wrong
  branch point makes the whole second-order check answer the wrong question, and the
  gate cannot catch a mis-conjectured feature — only an adversary can.
- **Skip** for a node already witnessed by the gate (the gate is the stronger signal),
  and for trivial restatements of an already-challenged prior.

## The volley (propose → challenge → refine → repeat)

Run rounds until convergence. Each round:

### 1. Fan out adversaries — every one tasked to REFUTE, not confirm

Use the Agent/Task tool to launch these concurrently (one message, multiple calls).
Each adversary defaults to **"refuted" under uncertainty** (adversarial-verify
discipline: a challenger that shrugs is a challenger that passed a bad prior).

- **Refuter.** For each open hypothesis, find the case it does **not** explain, the
  counter-evidence against it, the reason it is wrong. It is not asked "is this
  plausible" — it is asked to break it. If it cannot break a hypothesis after genuine
  effort, that hypothesis *survived this round* (it is not thereby verified).

- **Anti-anchor.** Propose hypotheses **not in the current set** — causes and operations
  the generator never considered. This is the direct fix for enumeration-anchoring: one
  conjecturer misses whole categories because they never entered its frame; an
  independent challenger walks out of the frame and names them. Do not rank against the
  existing set; *add* what is missing.

- **Framing challenger.** Attack the **case space** itself — is the inquiry even carved
  at the right joints? And where a **diff-the-diff branch point** was conjectured,
  challenge the *branch feature*: "is THIS the feature that splits the token-identical
  cases, or is it something else?" A surface-twin flip can have more than one candidate
  separating feature; the framing challenger names the rivals.

### 2. Cross-family by default

At least one challenger runs through a **different model family** via `codex exec`.
Same-family red-team is **weaker**: an adversary drawn from the generator's own
distribution shares its blind spots and anchors on the same few causes. A cross-family
challenger catches what the generator's distribution structurally can't — this matches
the paper's blind cross-family challenger pattern.

```bash
cat <<'EOF' | codex exec -
You are an adversarial reviewer. Do NOT confirm. Your job is to REFUTE.

Inquiry: <observation>
Open hypotheses (the priors), each a conjectured root cause:
  H1: <hypothesis text>
  H2: <hypothesis text>
  ...
(If a diff-the-diff branch is present:)
Conjectured branch feature: <feature> — the predicate claimed to split two
token-identical cases that demand opposite verdicts.

For EACH hypothesis: name the case it fails to explain, the counter-evidence, or
why it is wrong. Default to "refuted" if you are unsure — say what evidence would
change your mind. Then propose at least two root causes NOT in the list above
(operations the generator likely never considered). Finally, if a branch feature
is given, propose a rival feature that splits the same cases differently.

Output, per hypothesis: VERDICT (refuted / survived) + the refutation or the
specific counter-case. Then: ALTERNATIVES (not in the set). Then: RIVAL FEATURE.
EOF
```

**Degrade gracefully.** If `codex` is unavailable (not installed, no network, rate-
limited), fall back to a same-family Task adversary with the *same* refute-only brief,
and **note in the trail that the cross-family challenge was skipped** — a same-family
volley is weaker evidence and the record should say so, not hide it.

### 3. Integrate — refine the priors

Fold the challenges back into the open set:

- **Refuted hypothesis** → `kill` it, with the refutation (and which adversary raised
  it) as the recorded outcome. A dead node is information: keep it. The reader sees
  *why* a prior was abandoned and by whom, not merely that it vanished.
- **Surfaced alternative** (anti-anchor / rival feature) → add as a **new open node**.
  The frame just widened; the new prior enters the volley on the next round.
- **Survivor** → leave open, *strengthened*. Record that it survived red-team this round
  (and whether the cross-family challenger was in the round). Sharpen its statement if a
  challenge exposed vagueness without killing it.

### 4. Loop until dry

Re-run the volley on the updated open set. Stop after **two consecutive dry rounds** — a
round that kills nothing and surfaces no new alternative. Convergence means the priors
have stopped moving under adversarial pressure, not that they are correct.

## Record into the graph (the verifiable trail)

Use the existing hygraph operations — do **not** change verdict or gate logic, and do
not invent a new status.

```bash
# A refuted prior: killed, with the refutation as the recorded outcome.
abductor node kill <id> --graph "$GRAPH" \
    --outcome "refuted by <adversary>: <the counter-case / counter-evidence>"

# A surfaced alternative the generator anchored away from: a new OPEN node.
# kill_if is the falsifier the NEXT pass (or the gate) would run.
abductor node add "<alternative root cause not in the original set>" --graph "$GRAPH" \
    --trial "<how this would be tested — e.g. the gate command once built>" \
    --kill-if "<what evidence would refute this alternative>"

# A survivor: it stays open; note that it withstood red-team in this round. Append to
# the inquiry's audit surface (the .md sibling) rather than flipping a verdict — the
# gate, not red-team, is what earns a witness. A survived prior is stronger, not verified.
```

For a survivor, append a one-line note to the graph's markdown audit surface, e.g.
`survived red-team round N (cross-family: yes); sharpened: <restatement>`. Do **not**
`witness` a survivor — witnessing is for a gate-backed induction; surviving red-team is
adversarial pressure, not an oracle. Leaving it `open` keeps the honest claim: still a
conjecture, now a hardened one.

The result is a replayable adversarial trail. Even the un-checkable abductive step now
carries a record a stranger can re-read: every challenge, every refutation, every
alternative that walked out of the frame, and which challenges came cross-family.

## Discipline

- **Refute, don't confirm.** An adversary that sets out to validate a prior validates it.
  Default to refuted under uncertainty; make the prior earn survival.
- **Cross-family or say so.** A same-family volley is weaker evidence; if you degraded to
  it, the trail must record that, not paper over it.
- **Survival is not verification.** Red-team hardens a conjecture and surfaces rivals; it
  never makes abduction checkable. Keep survivors `open`.
- **Dead nodes stay.** A killed prior, with its refutation and its challenger, is the
  cheapest future warning against re-proposing it.
- **The graph is the interface.** Read open nodes in, write challenges back. This skill
  is general; it knows nothing about *which* inquiry it is hardening.
