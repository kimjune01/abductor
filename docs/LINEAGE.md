# Intellectual lineage

Abduction as a mode of inference is Peirce's (1878): abduction proposes a hypothesis, deduction traces its consequences, induction tests it. `abductor` mechanizes that loop with *ideas* — not source or text — drawn from the program-analysis tradition that put abduction to work, plus the statistical view of how to read a perturbation.

## Why prompting alone plateaus

A model told to "be general" or to "write its own tests" samples those tests from its current hypothesis, so the loop reaches a self-consistent narrow fixed point and never meets the surprising counterexample that would force revision — confirmation-biased hypothesis testing in the sense of Wason (1960). Optimizing a model against a metric it also authors is a Goodhart trap (Goodhart 1975; Strathern 1997). A *handed* gate fixes the objective before the hypothesis instead of sampling it from the hypothesis.

## Abduction in program analysis

- **Separation logic** — the substrate. Local reasoning about heap-manipulating programs: O'Hearn, Reynolds & Yang (2001); Reynolds (2002).
- **Bi-abduction** — infer a missing antecedent and a leftover frame at once, `P * ?antiframe ⊢ Q * ?frame`: Calcagno, Distefano, O'Hearn & Yang (2009/2011), the engine behind Meta's Infer (Calcagno et al., 2015).
- **Tri-abduction** — "a new type of inference" (their words) that synthesizes a single anti-frame `M` and two leftover frames `F1`, `F2` such that `M ⊨ P1 ∗ F1` and `M ⊨ P2 ∗ F2`: Outcome Separation Logic (Zilberstein, Saliling & Silva, 2024, §5.1). `abductor`'s `diff-the-diff` gate is the *checking analogue* of this synthesis — it borrows the two-distinct-leftover directional structure but does not infer the anti-frame, and its accept-set/heap correspondence is informal.
- **Incorrectness reasoning** — under-approximate logic for *finding* bugs rather than proving their absence: Incorrectness Logic (O'Hearn 2020), Incorrectness Separation Logic (Raad et al. 2020), and its scaling to real codebases (Le et al. 2022).
- **Counterexample-guided refinement (CEGAR)** — let a failing case drive the next abstraction: Clarke, Grumberg, Jha, Lu & Veith (2000).

## The disagreement structure

The gate computes a symmetric difference (an XOR) between *what the tool believes* and *what is true*. Compact representations for that:

- **Set reconciliation** — recover a symmetric difference from a small sketch: Eppstein, Goodrich, Uyeda & Varghese (2011); the BCH-syndrome secure sketch of Dodis, Reyzin & Smith (2004) that underlies Minisketch.
- **Zero-suppressed decision diagrams (ZDDs)** — compact families of sparse sets: Minato (1993).

## Reading the perturbation

- **Anytime-valid inference** — when each gate run is evidence in a sequence: sequential testing (Wald 1945), e-values (Vovk & Wang 2021), safe testing (Grünwald, de Heide & Koolen).
- **Method framing** — the hypothesis-graph and blind-merge dispatch patterns: J. Kim, *The Hypothesis Graph*, *Evidence has a trajectory*, *Modes of Reason*, *Blind, Blind, Merge* (june.kim).

## Clean-room note

`abductor` implements the *ideas* above as original expression. It does not copy source, algorithm listings, or text from Infer, Gillian, Broom, HIP/SLEEK, S2, SLAC, SLAyer, Quiver, FootPatch, or their papers.

## References

- C. S. Peirce (1878). *Deduction, Induction, and Hypothesis.* Popular Science Monthly 13:470–482.
- P. W. O'Hearn, J. C. Reynolds, H. Yang (2001). *Local Reasoning about Programs that Alter Data Structures.* CSL 2001.
- J. C. Reynolds (2002). *Separation Logic: A Logic for Shared Mutable Data Structures.* LICS 2002.
- C. Calcagno, D. Distefano, P. O'Hearn, H. Yang (2009/2011). *Compositional Shape Analysis by Means of Bi-Abduction.* POPL 2009; JACM 58(6), Article 26, 2011.
- C. Calcagno, D. Distefano, J. Dubreil, D. Gabi, P. Hooimeijer, M. Luca, P. O'Hearn, I. Papakonstantinou, J. Purbrick, D. Rodriguez (2015). *Moving Fast with Software Verification.* NASA Formal Methods (NFM), LNCS 9058, pp. 3–11.
- N. Zilberstein, A. Saliling, A. Silva (2024). *Outcome Separation Logic: Local Reasoning for Correctness and Incorrectness with Computational Effects.* PACMPL 8(OOPSLA1), Article 104. arXiv:2305.04842.
- P. O'Hearn (2020). *Incorrectness Logic.* PACMPL 4(POPL).
- A. Raad, J. Berdine, H.-H. Dang, D. Dreyer, P. O'Hearn, J. Villard (2020). *Local Reasoning About the Presence of Bugs: Incorrectness Separation Logic.* CAV 2020.
- Q. L. Le, A. Raad, J. Villard, J. Berdine, D. Dreyer, P. O'Hearn (2022). *Finding Real Bugs in Big Programs with Incorrectness Logic.* OOPSLA 2022.
- E. Clarke, O. Grumberg, S. Jha, Y. Lu, H. Veith (2000). *Counterexample-Guided Abstraction Refinement.* CAV 2000.
- D. Eppstein, M. T. Goodrich, F. Uyeda, G. Varghese (2011). *What's the Difference? Efficient Set Reconciliation without Prior Context.* SIGCOMM 2011.
- Y. Dodis, L. Reyzin, A. Smith (2004). *Fuzzy Extractors: How to Generate Strong Keys from Biometrics and Other Noisy Data.* EUROCRYPT 2004. (Full version, with R. Ostrovsky: SIAM J. Comput.; arXiv:cs/0602007. PinSketch / BCH set-difference secure sketch.)
- S. Minato (1993). *Zero-Suppressed BDDs for Set Manipulation in Combinatorial Problems.* DAC 1993.
- A. Wald (1945). *Sequential Tests of Statistical Hypotheses.* Annals of Mathematical Statistics 16(2):117–186.
- V. Vovk, R. Wang (2021). *E-values: Calibration, Combination, and Applications.* Annals of Statistics 49(3):1736–1754. arXiv:1912.06116.
- P. Grünwald, R. de Heide, W. Koolen (2024). *Safe Testing.* J. R. Stat. Soc. Series B (with discussion). arXiv:1906.07801.
- C. A. E. Goodhart (1975). *Problems of Monetary Management: The U.K. Experience.* Reserve Bank of Australia, Papers in Monetary Economics.
- M. Strathern (1997). *'Improving ratings': audit in the British University system.* European Review 5(3):305–321.
- P. C. Wason (1960). *On the failure to eliminate hypotheses in a conceptual task.* Quarterly Journal of Experimental Psychology 12(3):129–140.
- J. Kim. *The Hypothesis Graph; Evidence has a trajectory; Modes of Reason; Blind, Blind, Merge.* june.kim.

## Candidate lineage — maybes (unvetted)

Surfaced 2026-06-21 by an adversarial novelty fan-out over the soundness-gate application
(`enzyme-soundness-gate`). These are the *empirical software-engineering* ancestors and neighbours
of the gate, complementing the logic/statistics lineage above. Listed as candidates to vet before
promotion: each is real prior art, but its exact relationship to `abductor` (descends-from vs
empirical-precedent vs complementary-pole vs names-the-open-problem) still needs an author call.

- **Oracle-guided synthesis** *(lineage)* — the distinguishing-input → oracle-query loop: a minimal
  input on which two consistent hypotheses disagree, used to drive a query that elicits intent.
  This is the *synthesis-side* ancestor of the gate; `abductor` is its checking-side analogue (cf.
  the `diff-the-diff` note above). Jha, Gulwani, Seshia & Tiwari (2010), ICSE (Most Influential
  Paper).
- **Dynamic invariant detection** *(lineage)* — induction from observed executions to a likely
  invariant: the witness → property step a generalizer would mechanize. `abductor` would drive it
  from *externalized adversarial cases*, not passive runtime traces. Ernst et al., Daikon (SCP
  2007).
- **Test amplification** *(lineage)* — generalize a developer's existing test by mutating its
  inputs and synthesizing assertions. `abductor`'s per-rule input generalization adds
  rule-conditioned semantic axis selection (sign/tie/inf-nan/denormal) and a value+gradient oracle.
  Danglot, Vera-Pérez, Baudry & Monperrus, DSpot (EMSE 2019).
- **Differential AD testing** *(empirical precedent)* — differential testing of gradients across
  AD modes; 173 confirmed bugs, and a numerical false-positive filter that independently motivates
  the residue rubric (`abductor` *types* what this *drops*). Tests primitives, not optimize-then-AD
  compositions. Yang et al., NablaFuzz (ICSE 2023).
- **Rewrite verification** *(complementary pole)* — SMT proof that a peephole rewrite preserves
  semantics, incl. floating-point (signed zero, NaN, inf, denormal). The *verification* pole;
  `abductor` is the *testing* pole for transforms outside the decidable fragment (interprocedural
  differentiate-after-optimize). Lopes, Lee, Hur, Liu & Regehr, Alive2 (PLDI 2021); Menendez,
  Nagarakatte & Gupta, Alive-FP (SAS 2016); Nötzli & Brown, LifeJacket (2016, a precise-FP Alive
  fork — distinct from Alive-FP).
- **DL/tensor-compiler fuzzing** *(neighbouring field)* — optimization-soundness testing of tensor
  compilers, on forward/inference value equivalence; `abductor` would extend it to the backward
  pass. Liu et al., NNSmith (ASPLOS 2023); Tzer (OOPSLA/PACMPL 2022); MT-DLComp, *Metamorphic
  Testing of Deep Learning Compilers* (POMACS / SIGMETRICS 2022).
- **N-version with coding agents** *(names the open problem)* — finds that co-occurring faults in
  agent-generated versions trace to *specification ambiguity*, and closes with: "study how to use
  the correlated faults to detect and refine ambiguous specifications in an automated manner."
  `abductor`'s residue typing (tie / fast-math = genuine spec ambiguity) localizes what this only
  flags. Ron, Baudry & Monperrus (2026), arXiv:2606.20158.
- **Compiler-testing survey** *(names the open problem)* — §8 lists "test oracles beyond
  equivalence relations" among the open challenges; a gradient-preservation oracle is exactly a
  non-equivalence oracle sitting in that gap. Chen, Patra, Pradel, Xiong, Zhang, Hao & Zhang,
  *A Survey of Compiler Testing*, ACM Computing Surveys (2020).

- **Metamorphic testing** *(oracle construction without an exact oracle)* — when no reference
  exists, assert relations the output must satisfy under input transformations. The ancestor of the
  residue rubric's "this transform should preserve the verdict." Chen, Cheung & Yiu (1998); Segura
  et al. survey (2016).
- **Equivalence Modulo Inputs (EMI)** *(closest compiler-testing neighbour)* — mutate code that
  doesn't execute on a given input and require identical output; closer to `abductor`'s compiler
  gate than generic DL fuzzing. Le, Afshari & Su, PLDI 2014.
- **Delta debugging / C-Reduce** *(counterexample minimization)* — shrink a failing input to a
  minimal witness before handing it to abduction; a missing-but-central capability (see borrow
  list). Zeller & Hildebrandt (2002); Regehr et al., C-Reduce, PLDI 2012.
- **Translation validation** *(the verification frame Alive2 instantiates)* — prove a single
  compilation/transform instance correct rather than the compiler; name it explicitly, it is
  central not incidental. Pnueli, Siegel & Singerman (1998).
- **Property-based testing** *(generators + shrinking + executable properties)* — relevant only if
  `abductor` grows input generators rather than only reconciling given accept-sets. Claessen &
  Hughes, QuickCheck (2000).
