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


# A both-directions spec divergence: each oracle accepts something the other
# rejects. Reference is truth, base is the foil.  over-wide axis = BASE\REF = {4,16},
# over-narrow axis = REF\BASE = {3,9}; agreement set (cases both oracles accept) =
# {2,6,10,14,18}.
BD_BASE = [2, 4, 6, 10, 14, 16, 18]
BD_REF = [2, 3, 6, 9, 10, 14, 18]


def test_diff_the_diff_directional_verdicts():
    # diff-the-diff keeps the spec diff DIRECTIONAL and decomposes the candidate's
    # error Δ = C △ REF against the partition {core, over-wide, over-narrow}: pass (Δ empty),
    # disagree (Δ hits the agreement core), collapse_wide/narrow/both (Δ rides the
    # over-wide / over-narrow / both axes). Truth is --reference; --truth is the foil.
    with tempfile.TemporaryDirectory() as t:
        base, ref = f"{t}/base.txt", f"{t}/ref.txt"
        _write(base, BD_BASE)
        _write(ref, BD_REF)

        def ddd(accept):
            p = f"{t}/cand.txt"
            _write(p, accept)
            return run(["gate", "--believe", p, "--truth", base, "--reference", ref, "--json"])

        # spec diff is reported directionally and the same regardless of candidate
        code, out = ddd(BD_REF)
        d = json.loads(out)
        assert code == cli.EXIT_OK and d["verdict"] == "pass" and d["pass"] is True
        assert d["check"] == "diff-the-diff" and d["direction"] is None
        assert d["spec_diff"] == {"over_wide_axis": [4, 16], "over_narrow_axis": [3, 9]}

        # accepts a base-only case (4) -> collapse_wide on the over-wide axis
        code, out = ddd(BD_REF + [4])
        d = json.loads(out)
        assert code == cli.EXIT_COLLAPSE_WIDE
        assert d["verdict"] == "collapse_wide" and d["direction"] == "wide"
        assert d["over_wide"] == [4] and d["over_narrow"] == [] and d["core_errors"] == []

        # drops a reference-only case (3) -> collapse_narrow on the over-narrow axis
        code, out = ddd([x for x in BD_REF if x != 3])
        d = json.loads(out)
        assert code == cli.EXIT_COLLAPSE_NARROW
        assert d["verdict"] == "collapse_narrow" and d["over_narrow"] == [3]

        # both axes at once: accept 4 (base-only) and drop 3 (reference-only)
        code, out = ddd([x for x in BD_REF if x != 3] + [4])
        d = json.loads(out)
        assert code == cli.EXIT_COLLAPSE_BOTH
        assert d["direction"] == "both" and d["over_wide"] == [4] and d["over_narrow"] == [3]

        # wrong where the oracles AGREE (drops 2, a core case) -> plain disagree
        code, out = ddd([x for x in BD_REF if x != 2])
        d = json.loads(out)
        assert code == cli.EXIT_DISAGREE
        assert d["verdict"] == "disagree" and d["core_errors"] == [2]
        assert d["over_wide"] == [] and d["over_narrow"] == []


def test_diff_the_diff_provenance_present_and_stable():
    with tempfile.TemporaryDirectory() as t:
        base, ref, cand = f"{t}/base.txt", f"{t}/ref.txt", f"{t}/cand.txt"
        _write(base, BD_BASE)
        _write(ref, BD_REF)
        _write(cand, BD_REF + [4])
        argv = ["gate", "--believe", cand, "--truth", base, "--reference", ref, "--json"]
        out1 = json.loads(run(argv)[1])
        out2 = json.loads(run(argv)[1])
        prov = out1["provenance"]
        # all three roles fingerprinted with resolved path + sha256, plus exact argv
        assert set(prov["inputs"]) == {"candidate", "base", "reference"}
        assert prov["argv"] == ["abductor", *argv]
        for role in ("candidate", "base", "reference"):
            assert prov["inputs"][role]["path"].startswith("/")
            assert len(prov["inputs"][role]["sha256"]) == 64
        import hashlib
        assert prov["inputs"]["candidate"]["sha256"] == \
            hashlib.sha256(open(cand, "rb").read()).hexdigest()
        # stable: same inputs -> byte-identical provenance
        assert prov == out2["provenance"]


def test_collapse_codes_are_published():
    code, out = run(["codes", "--json"])
    d = json.loads(out)
    assert code == 0
    assert d[str(cli.EXIT_COLLAPSE_WIDE)].startswith("collapse_wide")
    assert d[str(cli.EXIT_COLLAPSE_NARROW)].startswith("collapse_narrow")
    assert d[str(cli.EXIT_COLLAPSE_BOTH)].startswith("collapse_both")


def test_node_probe_routes_a_collapse_as_collapsed_not_rc1():
    # A diff-the-diff collapse is a NON-TERMINAL verdict: `node probe` must classify
    # the node `collapsed` (carrying the direction) and return the collapse code, not
    # swallow it as an rc-1 errored trial. This is the control-poka-yoke seam.
    with tempfile.TemporaryDirectory() as t:
        base, ref, cand = f"{t}/base.txt", f"{t}/ref.txt", f"{t}/cand.txt"
        _write(base, BD_BASE)
        _write(ref, BD_REF)
        _write(cand, BD_REF + [4])  # collapse_wide
        graph = f"{t}/g.json"
        trial = (f"{PY} -m abductor gate --believe {cand} "
                 f"--truth {base} --reference {ref}")
        run(["graph", "init", "obs", "--graph", graph])
        code, _ = run(["node", "probe", "wide fix", "--graph", graph, "--trial", trial])
        assert code == cli.EXIT_COLLAPSE_WIDE      # routed on the collapse code, not rc1/error
        g = json.loads(run(["graph", "show", "--graph", graph, "--json"])[1])
        n = g["nodes"][0]
        assert n["status"] == "collapsed" and n["expected_exit"] == cli.EXIT_COLLAPSE_WIDE
        assert "collapse wide" in n["outcome"]
        # idempotent re-probe returns the same recorded collapse code
        code2, out2 = run(["node", "probe", "wide fix", "--graph", graph, "--trial", trial])
        assert code2 == cli.EXIT_COLLAPSE_WIDE and json.loads(out2).get("idempotent") is True
        # a collapsed node can name a successor (the agent re-enters by splitting)
        code3, _ = run(["node", "probe", "split on square-ness", "--from", "0",
                        "--graph", graph, "--trial", "exit 0"])
        assert code3 == cli.EXIT_OK
        g = json.loads(run(["graph", "show", "--graph", graph, "--json"])[1])
        assert g["nodes"][1]["parent_id"] == 0 and g["nodes"][1]["status"] == "witnessed"


def test_gate_single_oracle_output_unchanged_without_reference():
    # The second-order path must not perturb the existing single-oracle contract.
    with tempfile.TemporaryDirectory() as t:
        believe, truth = f"{t}/b.txt", f"{t}/tr.txt"
        _write(believe, [2, 4, 6])
        _write(truth, [2, 4, 6, 8])
        code, out = run(["gate", "--believe", believe, "--truth", truth, "--json"])
        d = json.loads(out)
        assert code == cli.EXIT_DISAGREE
        assert "second_order" not in d and d["false_negatives"] == [8]


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
