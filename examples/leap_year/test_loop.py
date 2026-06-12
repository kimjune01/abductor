"""Tests for the set-reconciliation gate and the hypothesis-graph CRUD.

Run:  uv run python -m pytest test_loop.py   (or just `uv run python test_loop.py`)
"""

from __future__ import annotations

from abductor.hygraph import HypothesisGraph, Mode, Status
from abductor.iblt import reconcile
from property import Gate, patch_1900, the_rule, true_leap


# --- set reconciliation (the parts-bin XOR) ----------------------------------

def test_reconcile_recovers_symmetric_difference():
    a = set(range(0, 1000))
    b = set(range(0, 1000)) - {7, 42, 800} | {1001, 1002}
    a_only, b_only, ok = reconcile(a, b)
    assert ok
    assert a_only == {7, 42, 800}      # in a, not b
    assert b_only == {1001, 1002}      # in b, not a
    assert (a_only, b_only) == (a - b, b - a)


def test_reconcile_empty_difference():
    a = b = set(range(500))
    a_only, b_only, ok = reconcile(a, b)
    assert ok and not a_only and not b_only


def test_reconcile_autogrows_when_sketch_too_small():
    a = set(range(2000))
    b = set(range(1000, 3000))  # difference of 2000 elements
    a_only, b_only, ok = reconcile(a, b, cells=8)  # deliberately tiny start
    assert ok
    assert a_only == a - b and b_only == b - a


# --- the gate ----------------------------------------------------------------

def test_gate_kills_narrow_patch():
    res = Gate(1, 2400).check(patch_1900)
    # The patch still calls other non-leap centuries leap (false positives).
    assert res.decoded and res.mishandled()
    assert all(not true_leap(y) for y in res.false_positives)
    assert 2100 in res.false_positives and 1900 not in res.mishandled()


def test_gate_witnesses_the_rule():
    res = Gate(1, 2400).check(the_rule)
    assert res.decoded and res.mishandled() == []


# --- hypothesis-graph CRUD ---------------------------------------------------

def test_create_caps_credence_at_mode():
    g = HypothesisGraph("obs")
    n = g.abduce("h", trial="t", kill_if="k", credence=0.99)
    assert n.mode is Mode.ABDUCTION and n.credence == 0.50  # capped


def test_update_is_write_once():
    g = HypothesisGraph("obs")
    n = g.abduce("h", trial="t", kill_if="k")
    g.kill(n, outcome="refuted")
    assert n.status is Status.KILLED and n.credence == 0.0
    try:
        g.witness(n, outcome="nope")
    except ValueError:
        pass
    else:
        raise AssertionError("expected write-once verdict to reject re-classification")


def test_link_requires_a_kill():
    g = HypothesisGraph("obs")
    parent = g.abduce("h", trial="t", kill_if="k")
    try:
        g.from_kill(parent, "child", trial="t2", kill_if="k2")
    except ValueError:
        pass
    else:
        raise AssertionError("open parent should not name a successor")
    g.kill(parent, outcome="dead")
    child = g.from_kill(parent, "child", trial="t2", kill_if="k2")
    assert child.parent_id == parent.id


def test_delete_leaves_frontier_but_keeps_record():
    g = HypothesisGraph("obs")
    n = g.abduce("h", trial="t", kill_if="k")
    g.prune(n)
    assert n not in g.frontier() and n in g.nodes


def test_probe_climbs_and_witnesses():
    gate = Gate(1, 2400)
    g = HypothesisGraph("year 1900 reported leap")
    n1, ce1 = g.probe("special-case 1900", patch_1900, gate)
    assert n1.status is Status.KILLED and ce1

    n3, ce3 = g.probe("the rule", the_rule, gate, parent=n1)
    assert n3.status is Status.WITNESSED and ce3 == []
    assert n3.mode is Mode.INDUCTION and n3.credence <= 0.97


def test_replay_holds_the_soundness_invariant():
    gate = Gate(1, 2400)
    g = HypothesisGraph("obs")
    n, _ = g.probe("the rule", the_rule, gate)
    matches, recorded, replayed = g.replay(n)
    assert matches and recorded == replayed == []


if __name__ == "__main__":
    import sys

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
