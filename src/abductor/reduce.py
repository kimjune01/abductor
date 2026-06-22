"""Delta debugging (ddmin) — shrink a divergent input to a minimal witness.

Pure mechanism, in keeping with rule #1 (the tool never judges): `reduce`
minimizes an input while a *handed* predicate stays true; it never decides what
the witness means. The predicate is a trial command (the same `--trial`
convention as `node probe`): the candidate is substituted into a ``{}``
placeholder (a temp-file path) or, absent a placeholder, fed on the trial's
stdin; the trial is "interesting" iff its exit code equals ``expect`` (default
10, a disagreement). So `reduce` answers "what is the smallest input that still
makes the gate fire," and hands that minimal witness to the agent.

ddmin (Zeller & Hildebrandt, 2002) returns a 1-minimal subsequence: no single
remaining unit can be dropped without losing the verdict. The trial is the cost,
so results are memoized by candidate string.
"""
from __future__ import annotations

import os
import subprocess
import tempfile

BASH = "/bin/bash"  # trials may use process substitution <(...), which needs bash


def split_units(text: str, unit: str) -> list[str]:
    if unit == "char":
        return list(text)
    if unit == "token":
        return text.split()
    return text.split("\n")  # line


def join_units(units: list[str], unit: str) -> str:
    if unit == "char":
        return "".join(units)
    if unit == "token":
        return " ".join(units)
    return "\n".join(units)


def run_predicate(trial: str, candidate: str, expect: int) -> bool:
    """True iff the trial, given `candidate`, exits with code `expect`."""
    if "{}" in trial:
        f = tempfile.NamedTemporaryFile("w", suffix=".cand", delete=False)
        try:
            f.write(candidate)
            f.close()
            cp = subprocess.run(trial.replace("{}", f.name), shell=True,
                                executable=BASH, capture_output=True, text=True)
        finally:
            os.unlink(f.name)
    else:
        cp = subprocess.run(trial, shell=True, executable=BASH, input=candidate,
                            capture_output=True, text=True)
    return cp.returncode == expect


def ddmin(units: list[str], interesting) -> list[str]:
    """Classic complement-based ddmin to 1-minimality.

    `interesting(list) -> bool` is supplied by the caller (memoized there).
    """
    n = 2
    while len(units) >= 2:
        chunk = max(1, len(units) // n)
        start = 0
        reduced = False
        while start < len(units):
            complement = units[:start] + units[start + chunk:]
            if complement and interesting(complement):
                units = complement
                n = max(n - 1, 2)
                reduced = True
                break
            start += chunk
        if not reduced:
            if n >= len(units):
                break
            n = min(len(units), n * 2)
    return units


def reduce_input(text: str, trial: str, expect: int, unit: str):
    """Minimize `text` (split by `unit`) to a 1-minimal witness.

    Returns (minimal_units, n_evals), or (None, n_evals) if the *full* input is
    not interesting to begin with — there is nothing to reduce, and silently
    returning the whole input would read as a successful minimization.
    """
    units = split_units(text, unit)
    cache: dict[str, bool] = {}
    evals = [0]

    def interesting(us: list[str]) -> bool:
        cand = join_units(us, unit)
        if cand in cache:
            return cache[cand]
        evals[0] += 1
        r = run_predicate(trial, cand, expect)
        cache[cand] = r
        return r

    if not interesting(units):
        return None, evals[0]
    return ddmin(units, interesting), evals[0]
