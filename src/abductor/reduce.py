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

Hazards the caller cannot remove (document, don't pretend to handle):
  - A non-monotonic or *flaky* trial breaks ddmin's core assumption; the witness is
    whatever was interesting once, and is not re-validated for stability.
  - A predicate satisfied by trivial input reduces to a trivial (possibly empty)
    witness.
  - `token` mode reduces over `text.split()` and rejoins with single spaces, so the
    candidate is NOT a byte-subsequence of the original: it collapses runs of
    whitespace, newlines, and tabs. Use it only for whitespace-insensitive inputs
    (e.g. an integer accept-set); use `line` or `char` when layout is load-bearing.
`reduce` surfaces a broken trial (exit 126/127, on the full input and as a count
during reduction), a timeout, and a blank witness, but it cannot tell a *wrong*
predicate from a right one.
"""
from __future__ import annotations

import os
import shlex
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


def run_trial(trial: str, candidate: str, timeout: float | None = None) -> int | None:
    """Run the trial on `candidate`; return its exit code, or None on timeout."""
    if "{}" in trial:
        f = tempfile.NamedTemporaryFile("w", suffix=".cand", delete=False)
        try:
            f.write(candidate)
            f.close()
            cmd = trial.replace("{}", shlex.quote(f.name))
            try:
                cp = subprocess.run(cmd, shell=True, executable=BASH,
                                    capture_output=True, text=True, timeout=timeout)
            except subprocess.TimeoutExpired:
                return None
        finally:
            os.unlink(f.name)
    else:
        try:
            cp = subprocess.run(trial, shell=True, executable=BASH, input=candidate,
                                capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return None
    return cp.returncode


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


def reduce_input(text: str, trial: str, expect: int, unit: str,
                 timeout: float | None = None) -> dict:
    """Minimize `text` (split by `unit`) to a 1-minimal witness.

    Returns a dict: ``minimal`` (the units, or None if the full input is not
    interesting), ``evals`` (trial count), and ``full_code`` (the exit code of the
    trial on the *full* input, or None if it timed out) so the caller can give an
    instructive message — a broken trial (126/127) or a timeout is reported as such,
    not silently mistaken for "does not reproduce".

    A trial that times out *during* reduction counts as not-interesting, so a hang
    can never be accepted as a smaller witness.
    """
    units = split_units(text, unit)
    cache: dict[str, bool] = {}
    evals = [0]
    broken = [0]  # trials that failed to RUN (126/127) during reduction

    def interesting(us: list[str]) -> bool:
        cand = join_units(us, unit)
        if cand in cache:
            return cache[cand]
        evals[0] += 1
        code = run_trial(trial, cand, timeout)
        if code in (126, 127):
            broken[0] += 1  # a smaller candidate broke the trial, not the predicate
        r = (code == expect)
        cache[cand] = r
        return r

    full_code = run_trial(trial, text, timeout)
    evals[0] += 1
    cache[text] = (full_code == expect)
    if full_code != expect:
        return {"minimal": None, "evals": evals[0], "full_code": full_code,
                "broken": 0}
    minimal = ddmin(units, interesting)
    # 1-minimality floor: ddmin's chunking never proposes the empty candidate, so
    # the last surviving unit is never tested for removal. If the predicate is still
    # interesting on empty input, that IS the minimum (and a sign of a too-weak trial).
    if minimal and interesting([]):
        minimal = []
    return {"minimal": minimal, "evals": evals[0], "full_code": full_code,
            "broken": broken[0]}
