"""Tests for `abductor reduce` (ddmin input minimization).

Standalone runner (no pytest needed):  uv run python tests/test_reduce.py
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
from contextlib import redirect_stdout

from abductor import cli


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(argv)
    return code, buf.getvalue()


def run_err(argv: list[str]) -> tuple[int, str]:
    """Run capturing stderr (where instructive failure messages go)."""
    from contextlib import redirect_stderr
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(argv)
    return code, err.getvalue()


def test_reduce_to_single_interesting_line():
    # Predicate: candidate still contains the line BAD (grep exit 0 = interesting).
    # ddmin should peel a 6-line input down to just BAD.
    with tempfile.TemporaryDirectory() as t:
        src = f"{t}/in.txt"
        with open(src, "w") as f:
            f.write("a\nb\nc\nBAD\nd\ne")
        code, out = run(["reduce", src, "--trial", "grep -qx BAD {}",
                         "--expect", "0", "--json"])
        d = json.loads(out)
        assert code == cli.EXIT_OK
        assert d["minimal"] == "BAD"
        assert d["minimal_units"] == 1 and d["original_units"] == 6


def test_reduce_errors_when_full_input_does_not_reproduce():
    # No BAD anywhere -> the full input is not interesting -> nothing to reduce.
    with tempfile.TemporaryDirectory() as t:
        src = f"{t}/in.txt"
        with open(src, "w") as f:
            f.write("a\nb\nc")
        code, out = run(["reduce", src, "--trial", "grep -qx BAD {}", "--expect", "0"])
        assert code == cli.EXIT_ERROR


def test_reduce_feeds_candidate_on_stdin_without_placeholder():
    # No {} placeholder -> candidate is piped to the trial's stdin.
    with tempfile.TemporaryDirectory() as t:
        src = f"{t}/in.txt"
        with open(src, "w") as f:
            f.write("x\ny\nKEEP\nz")
        code, out = run(["reduce", src, "--trial", "grep -qx KEEP",
                         "--expect", "0", "--json"])
        d = json.loads(out)
        assert code == cli.EXIT_OK and d["minimal"] == "KEEP"


def test_reduce_token_unit_minimizes_a_set():
    # Whitespace tokens (e.g. an accept-set): keep minimizing while token 7 present.
    with tempfile.TemporaryDirectory() as t:
        src = f"{t}/set.txt"
        with open(src, "w") as f:
            f.write("1 2 3 7 8 9")
        code, out = run(["reduce", src, "--trial", "grep -qw 7 {}",
                         "--expect", "0", "--unit", "token", "--json"])
        d = json.loads(out)
        assert code == cli.EXIT_OK and d["minimal"] == "7" and d["unit"] == "token"


def test_reduce_writes_out_file():
    with tempfile.TemporaryDirectory() as t:
        src, dst = f"{t}/in.txt", f"{t}/min.txt"
        with open(src, "w") as f:
            f.write("p\nBAD\nq")
        code, _ = run(["reduce", src, "--trial", "grep -qx BAD {}",
                       "--expect", "0", "--out", dst, "--json"])
        assert code == cli.EXIT_OK
        assert open(dst).read() == "BAD"


def test_reduce_is_1_minimal_with_two_required_units():
    # Predicate needs BOTH A and B present -> minimal must keep exactly those two.
    with tempfile.TemporaryDirectory() as t:
        src = f"{t}/in.txt"
        with open(src, "w") as f:
            f.write("w\nA\nx\ny\nB\nz")
        # interesting iff both A and B are present
        trial = "grep -qx A {} && grep -qx B {}"
        code, out = run(["reduce", src, "--trial", trial, "--expect", "0", "--json"])
        d = json.loads(out)
        assert code == cli.EXIT_OK
        assert d["minimal"] == "A\nB" and d["minimal_units"] == 2


def test_reduce_surfaces_exit_code_when_not_reproducing():
    # Trial exits 3 on the full input; --expect 10. Message must name the real code.
    with tempfile.TemporaryDirectory() as t:
        src = f"{t}/in.txt"
        with open(src, "w") as f:
            f.write("a\nb\nc")
        code, err = run_err([
            "reduce", src, "--trial", "exit 3", "--expect", "10"])
        assert code == cli.EXIT_ERROR
        assert "exited 3" in err and "does not reproduce" in err


def test_reduce_detects_a_broken_trial():
    # A command-not-found trial (exit 127) must be reported as broken, not as
    # "does not reproduce" (the classic delta-debugging footgun).
    with tempfile.TemporaryDirectory() as t:
        src = f"{t}/in.txt"
        with open(src, "w") as f:
            f.write("a\nb")
        code, err = run_err([
            "reduce", src, "--trial", "no_such_cmd_xyz {}", "--expect", "0"])
        assert code == cli.EXIT_ERROR
        assert "127" in err and "failed to run" in err


def test_reduce_reaches_empty_when_predicate_is_trivially_true():
    # A too-weak predicate (always exit 0) is interesting on empty input; true
    # 1-minimality must reduce all the way to empty, and warn it is blank.
    with tempfile.TemporaryDirectory() as t:
        src = f"{t}/in.txt"
        with open(src, "w") as f:
            f.write("a\nb\nc")
        code, out = run(["reduce", src, "--trial", "true", "--expect", "0", "--json"])
        d = json.loads(out)
        assert code == cli.EXIT_OK and d["minimal_units"] == 0 and d["minimal"] == ""
        _, err = run_err(["reduce", src, "--trial", "true", "--expect", "0"])
        assert "empty or whitespace-only" in err


def test_reduce_warns_when_a_smaller_candidate_breaks_the_trial():
    # Trial works on the full input but exits 127 on any single-token candidate.
    # Reduction is blocked there; reduce must warn rather than hide it.
    with tempfile.TemporaryDirectory() as t:
        src = f"{t}/set.txt"
        with open(src, "w") as f:
            f.write("1 2 7 8 9")
        trial = 'if [ "$(wc -w < {})" -le 1 ]; then exit 127; fi; grep -qw 7 {}'
        code, err = run_err(["reduce", src, "--trial", trial, "--expect", "0",
                             "--unit", "token"])
        assert code == cli.EXIT_OK and "failed to run" in err and "during reduction" in err


def test_reduce_times_out_on_a_hanging_trial():
    with tempfile.TemporaryDirectory() as t:
        src = f"{t}/in.txt"
        with open(src, "w") as f:
            f.write("a\nb")
        code, err = run_err([
            "reduce", src, "--trial", "sleep 5", "--expect", "0", "--timeout", "0.5"])
        assert code == cli.EXIT_ERROR and "timed out" in err


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
