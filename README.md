# abductor

Execution-gated abductive evaluation for LLM-driven program repair and verification.

## What it is

When an LLM fixes a bug whose correct fix is a *predicate* (not a single case), it tends to **tabulate** — patch the reported example and a few neighbours — rather than **represent** the underlying property. Prompting it to "be general" or to "verify itself" does not reliably close that gap: a self-built test set is sampled from the model's own hypothesis, so the loop converges to a self-consistent narrow fixed point and never receives the surprising counterexample that would force revision (confirmation-biased hypothesis testing, in the sense of Wason 1960).

`abductor` externalizes the evaluation. It enumerates a broad, fixpoint-closed space of cases for the property under repair, calibrates each against a known-good baseline, and exposes a pass/fail gate the model hill-climbs against. The gate carries *external* ground truth, so its coverage — not the model's prior — sets the generalization frontier. Optimizing a model against a metric it also authors is a Goodhart trap (Goodhart 1975; Strathern 1997); a handed gate fixes the objective before the hypothesis instead.

In a case study (a real soundness bug in the verus verifier), an executable gate of this shape moved a strong model from a narrow `!`-only fix to a general one that delegated to the verifier's own inhabitedness oracle, where six prompt-encoded reasoning methods stayed narrow.

The recurring target is an XOR-shaped predicate — two conditions that must *disagree* — i.e. a symmetric-difference / completeness check that unit tests and type systems structurally cannot provide, because absence has no test.

## Intellectual lineage

Abduction as a mode of inference is Peirce's (1878): abduction proposes a hypothesis, deduction traces its consequences, induction tests it. `abductor` mechanizes the loop with ideas — not source or text — drawn from the program-analysis tradition that put abduction to work:

- **Bi-abduction** — inferring a missing antecedent and a leftover frame simultaneously, `P * ?antiframe ⊢ Q * ?frame` — from Calcagno, Distefano, O'Hearn & Yang (POPL 2009; JACM 2011), the engine behind Facebook/Meta's Infer (Calcagno et al., NFM 2015). Built on separation logic (Reynolds, LICS 2002; O'Hearn, Reynolds & Yang).
- **Tri-abduction** — composing two branches with one shared antecedent and per-branch frames — from Outcome Separation Logic (Zilberstein et al., OOPSLA 2024; arXiv:2305.04842, §5.1).
- **Incorrectness reasoning** — under-approximate logic for *finding* bugs rather than proving their absence: Incorrectness Logic (O'Hearn, POPL 2020), Incorrectness Separation Logic (Raad et al., CAV 2020), and its scaling to real codebases (Le et al., "Finding Real Bugs… with Incorrectness Logic," OOPSLA 2022).
- **Counterexample-guided refinement (CEGAR)** — let a failing case drive the next abstraction — Clarke, Grumberg, Jha, Lu & Veith (CAV 2000).

Compact representations for the symmetric-difference / disagreement structure the gate computes:

- **Set reconciliation** — recover a symmetric difference from a small sketch: Eppstein, Goodrich, Uyeda & Varghese (SIGCOMM 2011), and the BCH-syndrome approach of Dodis, Reyzin & Smith (EUROCRYPT 2004) that underlies Minisketch (Wuille et al.).
- **Zero-suppressed decision diagrams (ZDDs)** — compact families of sparse sets: Minato (DAC 1993).

Methodology — how a perturbation is run and read:

- **Evidence trajectories & anytime-valid inference** — sequential testing (Wald 1945), e-values (Vovk & Wang, *Ann. Statist.* 2021), safe testing (Grünwald, de Heide & Koolen).
- The hypothesis-graph framing and the blind-merge dispatch pattern: J. Kim, *The Hypothesis Graph*, *Evidence has a trajectory*, *Modes of Reason*, *Blind, Blind, Merge* (june.kim).

## Status

Early. Originated as the `case-check` tool in the verus case study; this repo is its clean-room home. Code here is original expression that implements the *ideas* above without copying source, algorithm listings, or text from Infer, Gillian, Broom, HIP/SLEEK, S2, SLAC, SLAyer, Quiver, FootPatch, or their papers.

## Layout

- `src/abductor/` — the library/CLI
- `docs/` — design notes and the idea lineage

## Development

Uses `uv`.

```
uv run abductor --help
```

## License

Copyright © 2026 June Kim. Licensed under the GNU Affero General Public License v3.0 (see [LICENSE](LICENSE)).

As the sole copyright holder, the author reserves the right to release this software under alternative terms (dual licensing); the AGPL-3.0 grant binds redistributors, not the author. External contributions are accepted only under a contributor license agreement that preserves this.

## References

- C. S. Peirce (1878). *Deduction, Induction, and Hypothesis.* Popular Science Monthly.
- J. C. Reynolds (2002). *Separation Logic: A Logic for Shared Mutable Data Structures.* LICS.
- C. Calcagno, D. Distefano, P. O'Hearn, H. Yang (2009/2011). *Compositional Shape Analysis by Means of Bi-Abduction.* POPL 2009; JACM 58(6).
- C. Calcagno, D. Distefano, et al. (2015). *Moving Fast with Software Verification.* NASA Formal Methods. (Infer)
- N. Zilberstein, et al. (2024). *Outcome Separation Logic.* OOPSLA. arXiv:2305.04842.
- P. O'Hearn (2020). *Incorrectness Logic.* POPL.
- A. Raad, J. Berdine, H.-H. Dang, D. Dreyer, P. O'Hearn, J. Villard (2020). *Local Reasoning About the Presence of Bugs: Incorrectness Separation Logic.* CAV.
- Q. L. Le, A. Raad, J. Villard, J. Berdine, D. Dreyer, P. O'Hearn (2022). *Finding Real Bugs in Big Programs with Incorrectness Logic.* OOPSLA.
- E. Clarke, O. Grumberg, S. Jha, Y. Lu, H. Veith (2000). *Counterexample-Guided Abstraction Refinement.* CAV.
- D. Eppstein, M. T. Goodrich, F. Uyeda, G. Varghese (2011). *What's the Difference? Efficient Set Reconciliation without Prior Context.* SIGCOMM.
- Y. Dodis, L. Reyzin, A. Smith (2004). *Fuzzy Extractors* (PinSketch / BCH set reconciliation). EUROCRYPT.
- S. Minato (1993). *Zero-Suppressed BDDs for Set Manipulation in Combinatorial Problems.* DAC.
- A. Wald (1945). *Sequential Tests of Statistical Hypotheses.* Ann. Math. Statist.
- V. Vovk, R. Wang (2021). *E-values: Calibration, Combination, and Applications.* Ann. Statist. 49(3).
- P. Grünwald, R. de Heide, W. Koolen. *Safe Testing.* J. R. Stat. Soc. B.
- P. C. Wason (1960). *On the failure to eliminate hypotheses in a conceptual task.* Q. J. Exp. Psychol.
- M. Strathern (1997). *'Improving ratings': audit in the British University system.* European Review. (Goodhart's law)
- J. Kim. *The Hypothesis Graph; Evidence has a trajectory; Modes of Reason; Blind, Blind, Merge.* june.kim.
