"""The toy under repair: a leap-year predicate.

A buggy predicate whose real fix is a *rule*, not a case patch. The classic
trap: ``year % 4 == 0`` is right for most years and wrong for centuries. Patch
the one failing case in the bug report and you stay narrow; the gate's coverage,
not the model's prior, has to drag the fix to the rule.

The gate holds the answer key the model cannot see (the calibrated baseline) and
exposes only the *disagreement* — computed by set reconciliation, never by
materializing both accept-sets.
"""

from __future__ import annotations

from dataclasses import dataclass

from abductor.iblt import reconcile


def true_leap(year: int) -> bool:
    """The calibrated baseline (the answer key). Divisible by 4, except centuries
    not divisible by 400."""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


# --- candidate fixes an agent might propose, narrow to general ----------------

def buggy(year: int) -> bool:
    """The shipped bug: every fourth year is leap."""
    return year % 4 == 0


def patch_1900(year: int) -> bool:
    """Narrow fix: special-case the year in the bug report."""
    return year % 4 == 0 and year != 1900


def no_centuries(year: int) -> bool:
    """Less narrow: centuries are never leap (overshoots — kills 2000)."""
    return year % 4 == 0 and year % 100 != 0


def the_rule(year: int) -> bool:
    """The general rule."""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


@dataclass
class GateResult:
    false_positives: set[int]  # candidate says leap, baseline says no
    false_negatives: set[int]  # baseline says leap, candidate says no
    decoded: bool              # did the sketch peel completely?

    def mishandled(self) -> list[int]:
        return sorted(self.false_positives | self.false_negatives)


@dataclass
class Gate:
    """The handed gate. Enumerates a case space once, then scores any candidate
    by reconciling its accept-set against the baseline's."""

    lo: int = 1
    hi: int = 2400

    def __post_init__(self) -> None:
        self.cases = list(range(self.lo, self.hi + 1))
        self.span = f"years {self.lo}..{self.hi}"
        # The baseline accept-set is computed once and reused across probes.
        self._truth = {y for y in self.cases if true_leap(y)}

    def check(self, candidate) -> GateResult:
        believed = {y for y in self.cases if candidate(y)}
        # Symmetric difference via set reconciliation (parts-bin), not `^`.
        # Only the O(d) sketch would cross a context/wire boundary in deployment.
        fp, fn, ok = reconcile(believed, self._truth)
        return GateResult(false_positives=fp, false_negatives=fn, decoded=ok)
