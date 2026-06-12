"""CLI-level tests: exit-code verdicts, global flags, probe, and exact-exit replay.

Standalone runner (no pytest needed):  uv run python tests/test_cli.py
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
from contextlib import redirect_stdout

from abductor import cli

PY = sys.executable
TRUTH = [y for y in range(1, 2401) if y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)]


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(argv)
    return code, buf.getvalue()


def _write(path: str, ys: list[int]) -> None:
    with open(path, "w") as f:
        f.write("\n".join(str(y) for y in ys))


def test_codes_is_machine_readable():
    code, out = run(["codes", "--json"])
    d = json.loads(out)
    assert code == 0 and d["10"].startswith("disagree") and d["0"].startswith("ok")


def test_gate_exit_codes_and_global_flag_position():
    with tempfile.TemporaryDirectory() as t:
        truth, patch = f"{t}/truth.txt", f"{t}/patch.txt"
        _write(truth, TRUTH)
        _write(patch, [y for y in range(1, 2401) if y % 4 == 0 and y != 1900])
        # --json BEFORE the subcommand must work
        code, out = run(["--json", "gate", "--believe", patch, "--truth", truth])
        assert code == cli.EXIT_DISAGREE
        assert 2100 in json.loads(out)["false_positives"]
        # agreement → exit 0
        code, _ = run(["gate", "--believe", truth, "--truth", truth, "--json"])
        assert code == cli.EXIT_OK


def test_probe_records_expected_exit_and_replay_is_exact():
    with tempfile.TemporaryDirectory() as t:
        truth = f"{t}/truth.txt"
        _write(truth, TRUTH)
        _write(f"{t}/rule.txt", TRUTH)
        _write(f"{t}/patch.txt", [y for y in range(1, 2401) if y % 4 == 0 and y != 1900])
        graph = f"{t}/g.json"
        gate = lambda f: f"{PY} -m abductor gate --believe {f} --truth {truth}"  # noqa: E731

        assert run(["graph", "init", "obs", "--graph", graph])[0] == 0
        # a wrong fix → killed, expected_exit recorded as 10
        code, _ = run(["node", "probe", "patch", "--graph", graph,
                       "--trial", gate(f"{t}/patch.txt"), "--kill-if", "any"])
        assert code == cli.EXIT_DISAGREE
        # the rule, linked from the kill → witnessed, expected_exit 0
        code, _ = run(["node", "probe", "rule", "--graph", graph, "--from", "0",
                       "--trial", gate(f"{t}/rule.txt"), "--kill-if", "any"])
        assert code == cli.EXIT_OK

        g = json.loads(run(["graph", "show", "--graph", graph, "--json"])[1])
        assert [n["expected_exit"] for n in g["nodes"]] == [10, 0]
        assert [n["status"] for n in g["nodes"]] == ["killed", "witnessed"]

        # replay checks the exact recorded code, not just zero/nonzero
        for nid in ("0", "1"):
            code, out = run(["replay", nid, "--graph", graph, "--json"])
            assert code == cli.EXIT_OK and json.loads(out)["reproduces"] is True


def test_replay_rejects_a_crash_as_a_kill():
    # A crashing trial (exit 127) must NOT count as reproducing a killed node.
    with tempfile.TemporaryDirectory() as t:
        graph = f"{t}/g.json"
        run(["graph", "init", "obs", "--graph", graph])
        run(["node", "probe", "bad", "--graph", graph,
             "--trial", "exit 10", "--kill-if", "any"])           # killed, expected 10
        code, out = run(["replay", "0", "--graph", graph, "--json"])
        # sanity: the recorded kill reproduces
        assert json.loads(out)["reproduces"] is True
        # now a node whose trial crashes instead of disagreeing
        run(["node", "add", "crashy", "--graph", graph, "--trial", "nonexistent_cmd_xyz",
             "--kill-if", "any"])
        run(["node", "kill", "1", "--graph", graph, "--outcome", "claimed"])
        code, out = run(["replay", "1", "--graph", graph, "--json"])
        # exit 127 != expected 10 → does not reproduce
        assert code == cli.EXIT_UNDECODED and json.loads(out)["reproduces"] is False


def test_idempotent_retries_do_not_duplicate():
    with tempfile.TemporaryDirectory() as t:
        graph = f"{t}/g.json"
        assert run(["graph", "init", "obs", "--graph", graph])[0] == 0
        assert run(["graph", "init", "obs", "--graph", graph])[0] == 0          # re-init no-op
        # re-init with a different observation is refused (not a silent overwrite)
        assert run(["graph", "init", "other", "--graph", graph])[0] == cli.EXIT_ERROR

        run(["node", "add", "h", "--graph", graph, "--trial", "true", "--kill-if", "k"])
        run(["node", "add", "h", "--graph", graph, "--trial", "true", "--kill-if", "k"])  # dup
        g = json.loads(run(["graph", "show", "--graph", graph, "--json"])[1])
        assert len(g["nodes"]) == 1                                             # not duplicated

        assert run(["node", "kill", "0", "--graph", graph, "--outcome", "x"])[0] == 0
        assert run(["node", "kill", "0", "--graph", graph, "--outcome", "x"])[0] == 0  # re-kill no-op
        # but flipping the verdict is still refused (write-once)
        assert run(["node", "witness", "0", "--graph", graph, "--outcome", "y"])[0] == cli.EXIT_ERROR


def test_idempotent_probe_does_not_rerun_or_duplicate():
    with tempfile.TemporaryDirectory() as t:
        graph = f"{t}/g.json"
        run(["graph", "init", "obs", "--graph", graph])
        a = run(["node", "probe", "h", "--graph", graph, "--trial", "exit 10"])
        b = run(["node", "probe", "h", "--graph", graph, "--trial", "exit 10"])  # retry
        assert a[0] == b[0] == cli.EXIT_DISAGREE
        assert json.loads(b[1]).get("idempotent") is True
        g = json.loads(run(["graph", "show", "--graph", graph, "--json"])[1])
        assert len(g["nodes"]) == 1


def test_save_is_atomic_and_writes_audit_copy():
    with tempfile.TemporaryDirectory() as t:
        graph = f"{t}/g.json"
        run(["graph", "init", "1900 reported leap", "--graph", graph])
        run(["node", "probe", "the rule", "--graph", graph, "--trial", "exit 0"])
        import os
        files = set(os.listdir(t))
        assert "g.json" in files and "g.md" in files            # substrate + audit copy
        assert not any(f.endswith(".tmp") for f in files)       # no leftover temp from atomic write
        md = open(f"{t}/g.md").read()
        assert "# Inquiry: 1900 reported leap" in md and "the rule" in md
        json.loads(open(graph).read())                          # json is valid (not truncated)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"ok   {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
