"""abductor — agent-first command line.

Design: clig.dev as the baseline, bent toward an agent in a debug loop rather
than a human at a prompt. See docs/CLI.md. Two rules carry the whole surface:

1. **The tool never judges.** Every command is a deterministic algorithmic
   operation over a cache — reconcile two sketches, append a node, replay a
   recorded command. Nothing here proposes a hypothesis, ranks a fix, or decides
   what a counterexample means. That is the agent's job. There is, on purpose, no
   `diagnose` and no `suggest`.
2. **The exit code is the verdict.** An agent routes on the status code without
   parsing: 0 = agreement / success, 10 = disagreement found, others below.

Output contract: the artifact goes to stdout as JSON (the default whenever stdout
is not a TTY; `--human` forces a table); narration and errors go to stderr; no
command ever prompts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys

from abductor.hygraph import HypothesisGraph, Mode, Status
from abductor.iblt import IBLT, reconcile, reconcile_sketches, sketch

# Exit codes — the verdict an agent routes on.
EXIT_OK = 0          # success / agreement (a hypothesis witnessed)
EXIT_ERROR = 1       # unexpected failure
# 2 is argparse's usage error
EXIT_NOTFOUND = 3    # graph or node not found
EXIT_UNDECODED = 4   # sketch too small to peel, or replay did not reproduce
EXIT_DISAGREE = 10   # a disagreement was found (a hypothesis killed)
# diff-the-diff: the candidate is right on the agreement core but collapsed onto one
# branch of a genuine spec divergence. Directional, so each axis gets its own code.
EXIT_COLLAPSE_WIDE = 11    # candidate sided with BASE on the over-wide axis
EXIT_COLLAPSE_NARROW = 12  # candidate sided with BASE on the over-narrow axis
EXIT_COLLAPSE_BOTH = 13    # candidate collapsed on both axes at once

# A collapse code -> the direction it names, for `node probe` routing.
COLLAPSE_DIRECTION = {
    EXIT_COLLAPSE_WIDE: "wide",
    EXIT_COLLAPSE_NARROW: "narrow",
    EXIT_COLLAPSE_BOTH: "both",
}

# The verdict table, published so an agent never scrapes docs for it.
EXIT_CODES = {
    EXIT_OK: "ok: success / agreement (a hypothesis witnessed)",
    EXIT_ERROR: "error: unexpected failure",
    2: "usage: bad arguments",
    EXIT_NOTFOUND: "not_found: graph or node missing",
    EXIT_UNDECODED: "undecoded: sketch too small, or a replay did not reproduce",
    EXIT_DISAGREE: "disagree: a disagreement was found (a hypothesis killed)",
    EXIT_COLLAPSE_WIDE: "collapse_wide: diff-the-diff — candidate sided with the base "
                        "on the over-wide axis (accepts cases the reference rejects)",
    EXIT_COLLAPSE_NARROW: "collapse_narrow: diff-the-diff — candidate sided with the "
                          "base on the over-narrow axis (drops cases the reference keeps)",
    EXIT_COLLAPSE_BOTH: "collapse_both: diff-the-diff — candidate collapsed onto the "
                        "base on both the over-wide and over-narrow axes",
}

DEFAULT_GRAPH = os.environ.get("ABDUCTOR_GRAPH", "inquiry.json")
BASH = "/bin/bash"  # trials may use process substitution <(...), which needs bash

DRIVING_CONTRACT = """\
the loop (you supply each hypothesis and trial; the tool reconciles and records):

  abductor graph init "the surprising observation"
  abductor node probe "a hypothesis" \\
      --trial "abductor gate --believe <(./fix) --truth truth.txt" --kill-if any
      # exit 10 -> killed (read the disagreement in trial_stdout, form the next one)
      # exit 0  -> witnessed; --from <id> links a node to the hypothesis it succeeds
  abductor replay <id>     # re-run the trial; reproduces iff the exit code matches

the exit code is the verdict (run `abductor codes`): 0 agree, 10 disagree.
JSON goes to stdout when piped; the graph is a small file (a checkpoint, not a DB).
"""


# -- output helpers -----------------------------------------------------------

def _use_json(args: argparse.Namespace) -> bool:
    if args.human:
        return False
    return True if args.json else not sys.stdout.isatty()


def emit(args: argparse.Namespace, data: dict, human: str) -> None:
    if _use_json(args):
        # Compact single-line JSON by default (one object per line, pipe-friendly);
        # --pretty expands it for a human reading the raw stream.
        if getattr(args, "pretty", False):
            json.dump(data, sys.stdout, indent=2, sort_keys=True)
        else:
            json.dump(data, sys.stdout, sort_keys=True, separators=(",", ":"))
        sys.stdout.write("\n")
    else:
        print(human)


def warn(msg: str) -> None:
    print(f"abductor: {msg}", file=sys.stderr)


def _preview(items: list, n: int = 5) -> str:
    """A human-line preview of a case-id list that never lies about magnitude:
    the leading count is always shown, so a 5-item cap can't read as the whole set
    (a `--human` row of `[1..5]` for an 80-element list is a 16x misread)."""
    head = items[:n]
    more = len(items) - len(head)
    body = ", ".join(map(str, head)) + (f", +{more} more" if more > 0 else "")
    return f"{len(items)}:[{body}]"


def read_ints(path: str) -> set[int]:
    """Read a whitespace-separated set of integers from a file or '-' (stdin)."""
    text = sys.stdin.read() if path == "-" else open(path).read()
    return {int(tok) for tok in text.split()}


def read_json(path: str) -> dict:
    return json.loads(sys.stdin.read() if path == "-" else open(path).read())


# -- gate: reconcile two accept-sets (the parts-bin XOR) ----------------------

def _load_accept(args: argparse.Namespace, path: str):
    """Load one accept-set as either a raw int set or an IBLT sketch."""
    return IBLT.from_dict(read_json(path)) if args.sketches else read_ints(path)


def _symdiff(args: argparse.Namespace, a, b):
    """Decompose the symmetric difference a △ b into (a \\ b, b \\ a, decoded).

    The one set primitive both gate paths share: a raw XOR locally, an O(d) IBLT
    reconcile across a boundary. ``a`` and ``b`` are already-loaded accept-sets, so
    the candidate is read once and reused across both reconciles in the diff-the-diff path.
    """
    if args.sketches:
        fp, fn, decoded = reconcile_sketches(a, b)
    else:
        fp, fn, decoded = reconcile(a, b, cells=args.cells)
    return (sorted(fp), sorted(fn), decoded) if decoded else (None, None, False)


def cmd_gate(args: argparse.Namespace) -> int:
    # Poka-yoke: gate is stateless (rule #1 — it reconciles, it never records). A
    # `--graph` here is a no-op, and a silent one reads as "the verdict was logged"
    # when nothing was. Say so, and name the command that does persist.
    if "--graph" in getattr(args, "_argv", []):
        warn("gate does not record to a graph; it only reconciles and exits a verdict. "
             "To persist this trial as a node, wrap it: "
             "`abductor node probe \"<hypothesis>\" --trial \"abductor gate ...\"`.")

    believe = _load_accept(args, args.believe)
    base_set = _load_accept(args, args.truth)

    if args.reference is not None:
        return _diff_the_diff(args, believe, base_set, _load_accept(args, args.reference))

    fp, fn, decoded = _symdiff(args, believe, base_set)
    if not decoded:
        warn("sketch too small to decode the difference; raise --cells")
        emit(args, {"decoded": False}, "undecoded: raise --cells")
        return EXIT_UNDECODED
    agree = not fp and not fn
    data = {
        "agree": agree,
        "delta": len(fp) + len(fn),
        "false_positives": fp,   # believed accept, oracle says no
        "false_negatives": fn,   # oracle says accept, candidate missed
        "decoded": True,
    }
    if agree:
        human = "agree: 0 disagreements"
    else:
        human = f"disagree: {data['delta']} cases  +{_preview(fp)} -{_preview(fn)}"
    emit(args, data, human)
    return EXIT_OK if agree else EXIT_DISAGREE


def _diff_the_diff(args: argparse.Namespace, believe, base_set, ref_set) -> int:
    """diff-the-diff: a directional, second-order symmetric-difference CHECK.

    The *checking analogue* of tri-abductive synthesis (OSL §5.1; Zilberstein,
    Saliling & Silva 2024). It borrows the two-distinct-leftover directional
    structure — the split that lets the verdict name *wide* vs *narrow* — but it
    does NOT implement the anti-frame inference, and the accept-set/heap
    correspondence is informal. Conjecturing the branch and supplying the two
    oracles is the model's abductive job; this gate only checks. The two axis
    sets below (`base_only`, `ref_only`) are diff-the-diff's own sets, not OSL's
    anti-frame M or its leftover frames.

    The spec's own diff is the reference (truth) against the base (the foil),
    kept DIRECTIONAL:

      base_only = BASE \\ REF   (over-wide axis: cases BASE accepts, REF rejects)
      ref_only  = REF \\ BASE   (over-narrow axis: cases REF accepts, BASE rejects)

    The candidate's error against truth, Δ = C △ REF, is decomposed against that
    partition. Where Δ lands names *how* the candidate collapsed the divergence:
    on the over-wide axis (sides with a too-wide base), the over-narrow axis, both,
    or off the axes entirely (a plain disagreement on the agreement core). The tool
    only decomposes; the model conjectures the hidden branch feature that splits the
    two oracles.
    """
    # The spec diff: reference is truth, base is the foil. Directional.
    base_only_l, ref_only_l, dec_spec = _symdiff(args, base_set, ref_set)  # BASE\REF, REF\BASE
    if not dec_spec:
        warn("sketch too small to decode the spec diff (base vs reference); raise --cells")
        emit(args, {"decoded": False}, "undecoded: raise --cells")
        return EXIT_UNDECODED
    # The candidate's diff against truth: c_over = C\REF, c_under = REF\C.
    c_over, c_under, dec_cand = _symdiff(args, believe, ref_set)
    if not dec_cand:
        warn("sketch too small to decode the candidate diff (believe vs reference); raise --cells")
        emit(args, {"decoded": False}, "undecoded: raise --cells")
        return EXIT_UNDECODED

    base_only, ref_only = set(base_only_l), set(ref_only_l)
    delta = set(c_over) | set(c_under)
    over_wide = sorted(set(c_over) & base_only)    # C accepts a base-only case (sides wide)
    over_narrow = sorted(set(c_under) & ref_only)  # C drops a reference-only case (sides narrow)
    core_errors = sorted(delta - base_only - ref_only)  # error where base and reference agree
    # The headline FP question for a LAYERED change: did the candidate ADD false
    # positives, or only inherit the base's? introduced_wide = C \ REF \ BASE — accepts
    # neither oracle wants, present in neither. It is the new-FP slice of core_errors
    # (c_over off the base-only axis), so over_wide=N (inherited) can hide introduced=0.
    introduced_wide = sorted(set(c_over) - base_only)

    if not delta:
        verdict, direction, rc = "pass", None, EXIT_OK
    elif core_errors:
        verdict, direction, rc = "disagree", None, EXIT_DISAGREE
    elif over_wide and over_narrow:
        verdict, direction, rc = "collapse_both", "both", EXIT_COLLAPSE_BOTH
    elif over_wide:
        verdict, direction, rc = "collapse_wide", "wide", EXIT_COLLAPSE_WIDE
    else:
        verdict, direction, rc = "collapse_narrow", "narrow", EXIT_COLLAPSE_NARROW

    data = {
        "check": "diff-the-diff",
        "second_order": True,
        "pass": rc == EXIT_OK,
        "verdict": verdict,
        "direction": direction,           # wide | narrow | both | null
        "candidate_delta": len(delta),
        "over_wide": over_wide,            # Δ ∩ base_only: base-only cases C wrongly accepts
        "over_narrow": over_narrow,        # Δ ∩ ref_only: reference-only cases C wrongly drops
        "core_errors": core_errors,        # Δ off both axes: wrong where the oracles agree
        "introduced_wide": introduced_wide,  # C\REF\BASE: NEW false positives this change added
        "spec_diff": {                     # the directional diff of the two oracles
            "over_wide_axis": base_only_l,    # BASE \ REF
            "over_narrow_axis": ref_only_l,   # REF \ BASE
        },
        "provenance": _provenance(args),
        "decoded": True,
    }
    if verdict == "pass":
        human = "pass: candidate matches the reference (truth)"
    elif verdict == "disagree":
        human = (f"disagree: {len(core_errors)} error(s) on the agreement core "
                 f"{_preview(core_errors)} (introduced_wide={_preview(introduced_wide)})")
    else:
        human = (f"{verdict}: collapsed {direction}  "
                 f"over_wide={_preview(over_wide)} over_narrow={_preview(over_narrow)} "
                 f"introduced_wide={_preview(introduced_wide)}")
    emit(args, data, human)
    return rc


def _sha256(path: str) -> str | None:
    """Hex digest of a file's bytes, or None for stdin ('-'), which is not
    replayable by path so it cannot be fingerprinted from the artifact alone."""
    if path == "-":
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _provenance(args: argparse.Namespace) -> dict:
    """A compact replay record: the exact argv plus a resolved path + sha256 for
    each oracle and the candidate, so a stranger can audit the verdict from the
    artifact alone (the verifiable-knowledge requirement)."""
    roles = {"candidate": args.believe, "base": args.truth, "reference": args.reference}
    return {
        "argv": ["abductor", *getattr(args, "_argv", [])],
        "inputs": {
            role: {"path": p if p == "-" else os.path.abspath(p), "sha256": _sha256(p)}
            for role, p in roles.items() if p is not None
        },
    }


# -- sketch: encode a set into an O(cells) blob for boundary crossing ----------

def cmd_sketch(args: argparse.Namespace) -> int:
    items = read_ints(args.infile)
    s = sketch(items, cells=args.cells, k=args.k)
    blob = json.dumps(s.to_dict(), indent=2) + "\n"
    if args.out:
        open(args.out, "w").write(blob)
        emit(args, {"cells": args.cells, "k": args.k, "out": args.out},
             f"wrote {args.cells}-cell sketch to {args.out}")
    else:
        sys.stdout.write(blob)
    return EXIT_OK


# -- graph: the inquiry's semantic memory -------------------------------------

def _load(args: argparse.Namespace) -> HypothesisGraph | None:
    if not os.path.exists(args.graph):
        warn(f"no graph at {args.graph}; run `abductor graph init` first")
        return None
    return HypothesisGraph.load(args.graph)


def cmd_graph_init(args: argparse.Namespace) -> int:
    if os.path.exists(args.graph) and not args.force:
        existing = HypothesisGraph.load(args.graph)
        if existing.observation == args.observation:
            # Idempotent: a retried init with the same observation is a no-op,
            # not an error, so a crashed-and-retried agent recovers cleanly.
            emit(args, existing.to_dict(), f"inquiry already initialized at {args.graph}")
            return EXIT_OK
        warn(f"{args.graph} holds a different inquiry ({existing.observation!r}); "
             f"pass --force to overwrite it, or use a different --graph path")
        return EXIT_ERROR
    g = HypothesisGraph(observation=args.observation)
    g.save(args.graph)
    emit(args, g.to_dict(), f"initialized inquiry at {args.graph}")
    return EXIT_OK


def cmd_graph_show(args: argparse.Namespace) -> int:
    g = _load(args)
    if g is None:
        return EXIT_NOTFOUND
    if args.markdown:
        print(g.to_markdown())
    else:
        emit(args, g.to_dict(), g.to_markdown())
    return EXIT_OK


# -- node: create / classify / link / prune -----------------------------------

def _node_dict(g: HypothesisGraph, node) -> dict:
    return next(n for n in g.to_dict()["nodes"] if n["id"] == node.id)


def _node(g: HypothesisGraph, nid: int):
    """Return node nid, or None after printing an instructive not-found message."""
    if 0 <= nid < len(g.nodes):
        return g.nodes[nid]
    n = len(g.nodes)
    where = f"ids 0..{n - 1}" if n else "no nodes yet"
    warn(f"no node #{nid}. The graph has {n} ({where}); see them with "
         f"`abductor graph show`, or start one with `abductor node probe`.")
    return None


def _parent_ok(g: HypothesisGraph, pid: int):
    """Resolve a --from parent, or None after an instructive message."""
    p = _node(g, pid)
    if p is None:
        return None
    if p.status not in (Status.KILLED, Status.COLLAPSED):
        warn(f"can't link to #{pid}: it is {p.status.value}, and a successor links only "
             f"from a killed or collapsed hypothesis. Kill it first "
             f"(`abductor node kill {pid} --outcome ...`), or drop --from for a fresh node.")
        return None
    return p


def cmd_node_add(args: argparse.Namespace) -> int:
    g = _load(args)
    if g is None:
        return EXIT_NOTFOUND
    dup = g.match(args.hypothesis, args.trial, args.from_node)
    if dup is not None:  # idempotent: a retried append returns the same node
        emit(args, _node_dict(g, dup), f"#{dup.id} already present (idempotent)")
        return EXIT_OK
    if args.from_node is not None:
        if _parent_ok(g, args.from_node) is None:
            return EXIT_ERROR
        node = g.from_kill(args.from_node, args.hypothesis, trial=args.trial,
                           kill_if=args.kill_if, credence=args.credence)
    else:
        node = g.abduce(args.hypothesis, trial=args.trial, kill_if=args.kill_if,
                        credence=args.credence, mode=Mode(args.mode))
    g.save(args.graph)
    emit(args, _node_dict(g, node), f"added #{node.id} ({node.mode.value})")
    return EXIT_OK


def _classify(args: argparse.Namespace, witness: bool) -> int:
    g = _load(args)
    if g is None:
        return EXIT_NOTFOUND
    node = _node(g, args.id)
    if node is None:
        return EXIT_NOTFOUND
    target = Status.WITNESSED if witness else Status.KILLED
    if node.status is target:
        # Idempotent: re-applying the same verdict is a no-op, not an error.
        emit(args, _node_dict(g, node), f"#{node.id} already {node.status.value} (idempotent)")
        return EXIT_OK
    if node.status is not Status.OPEN:
        nxt = f" --from {args.id}" if node.status is Status.KILLED else ""
        warn(f"#{args.id} is already {node.status.value}; verdicts are write-once. "
             f"Record the next step as a new node: "
             f"`abductor node probe \"<hypothesis>\"{nxt} --trial ...`.")
        return EXIT_ERROR
    node = (g.witness(node, outcome=args.outcome, credence=args.credence)
            if witness else g.kill(node, outcome=args.outcome))
    g.save(args.graph)
    emit(args, _node_dict(g, node), f"#{node.id} -> {node.status.value}")
    return EXIT_OK


def cmd_node_kill(args: argparse.Namespace) -> int:
    return _classify(args, witness=False)


def cmd_node_witness(args: argparse.Namespace) -> int:
    return _classify(args, witness=True)


def cmd_node_prune(args: argparse.Namespace) -> int:
    g = _load(args)
    if g is None:
        return EXIT_NOTFOUND
    node = _node(g, args.id)
    if node is None:
        return EXIT_NOTFOUND
    g.prune(node)
    g.save(args.graph)
    emit(args, _node_dict(g, node), f"#{node.id} pruned (record kept)")
    return EXIT_OK


def _run_trial(trial: str) -> subprocess.CompletedProcess:
    return subprocess.run(trial, shell=True, executable=BASH, capture_output=True, text=True)


def _branch_fields(stdout: str) -> dict | None:
    """If the trial was a diff-the-diff gate, pull its directional structure out of the
    stdout JSON so the node can record it. Returns None for any other trial (plain
    gate, `exit 0`, non-JSON), so single-oracle nodes are untouched. The verdict logic
    stays in the gate; this only relays what the gate already decided."""
    try:
        d = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(d, dict) or d.get("check") != "diff-the-diff":
        return None
    return {
        "verdict": d["verdict"],
        "over_wide": d.get("over_wide", []),
        "over_narrow": d.get("over_narrow", []),
        "core": d.get("core_errors", []),
    }


def cmd_node_probe(args: argparse.Namespace) -> int:
    """Append a hypothesis, run its trial, and classify by the trial's exit code.

    The fused create -> test -> classify step. The mechanical rule: a trial exiting
    0 witnesses the node, 10 kills it, and a diff-the-diff collapse code (11/12/13)
    classifies it *collapsed* — a non-terminal verdict that carries the direction and
    can name a successor (the agent re-enters by conjecturing the branch feature);
    any other code is a broken trial, left open. The agent still supplies the
    hypothesis and the trial — only the bookkeeping is fused. The trial's exit code
    is recorded so `replay` can check exact reproduction.
    """
    g = _load(args)
    if g is None:
        return EXIT_NOTFOUND
    node = g.match(args.hypothesis, args.trial, args.from_node)
    if node is not None and node.status is not Status.OPEN:
        # Idempotent: this probe already ran and was classified. Return the
        # recorded verdict without re-running the trial or duplicating the node.
        result = _node_dict(g, node)
        result["exit_code"] = node.expected_exit
        result["idempotent"] = True
        emit(args, result, f"#{node.id} already {node.status.value} (idempotent)")
        if node.status is Status.WITNESSED:
            return EXIT_OK
        if node.status is Status.COLLAPSED:
            return node.expected_exit  # the recorded collapse code (11/12/13)
        return EXIT_DISAGREE
    if node is None:
        if args.from_node is not None:
            if _parent_ok(g, args.from_node) is None:
                return EXIT_ERROR
            node = g.from_kill(args.from_node, args.hypothesis, trial=args.trial,
                               kill_if=args.kill_if, credence=args.credence)
        else:
            node = g.abduce(args.hypothesis, trial=args.trial, kill_if=args.kill_if,
                            credence=args.credence)
    # else: node exists but is still OPEN (a prior trial errored) — re-run on it.

    proc = _run_trial(args.trial)
    rc = proc.returncode
    # The graph records only the hypothesis-level verdict — a short mechanical
    # outcome and the expected exit. The trial's output (the disagreement, the
    # "diff") is regenerable by replay, so it is passed through to the agent here
    # but never stored.
    if rc == EXIT_OK:
        g.witness(node, outcome="trial exit 0")
        node.expected_exit = EXIT_OK
    elif rc == EXIT_DISAGREE:
        g.kill(node, outcome="trial exit 10")
        node.expected_exit = EXIT_DISAGREE
    elif rc in COLLAPSE_DIRECTION:
        # A diff-the-diff collapse: a non-terminal verdict, not a broken trial. The
        # node is classified `collapsed` with its direction; the agent routes on the
        # code (re-enters), it is never swallowed as an rc-1 error.
        g.collapse(node, outcome=f"trial exit {rc} (collapse {COLLAPSE_DIRECTION[rc]})")
        node.expected_exit = rc
    else:
        node.outcome = f"trial errored (exit {rc}); left open"
    # If the trial was a diff-the-diff gate, record its directional structure on the
    # node (verdict + per-axis offending case-IDs) so the branch-composition reasoning
    # is emitted as a queryable, replayable node — not a trust-me log line.
    branch = _branch_fields(proc.stdout)
    if branch is not None:
        g.annotate_branch(node, verdict=branch["verdict"], over_wide=branch["over_wide"],
                          over_narrow=branch["over_narrow"], core=branch["core"])
    g.save(args.graph)
    result = _node_dict(g, node)
    result["exit_code"] = rc
    result["trial_stdout"] = proc.stdout.strip()  # transient: read it, do not expect it stored
    terminal = (EXIT_OK, EXIT_DISAGREE, *COLLAPSE_DIRECTION)
    if rc not in terminal:
        result["stderr_tail"] = proc.stderr.strip()[-400:]
        warn(f"trial exited {rc}, not 0/10 or a collapse code (11/12/13); #{node.id} left "
             f"open. The trial must run a check that exits 0 (agree), 10 (disagree), or a "
             f"diff-the-diff collapse code, e.g. `abductor gate ...`. Fix --trial and probe again.")
    emit(args, result, f"#{node.id} probe rc={rc} -> {node.status.value}\n{proc.stdout.strip()}")
    return rc if rc in terminal else EXIT_ERROR


# -- replay: re-run a node's recorded trial command ---------------------------

def cmd_replay(args: argparse.Namespace) -> int:
    g = _load(args)
    if g is None:
        return EXIT_NOTFOUND
    node = _node(g, args.id)
    if node is None:
        return EXIT_NOTFOUND
    proc = _run_trial(node.trial)
    rc = proc.returncode
    # Reproduction is exact when an expected code was recorded (by `node probe`);
    # otherwise fall back to the status convention (witnessed -> 0, killed -> 10).
    expected = node.expected_exit
    if expected is None:
        expected = EXIT_OK if node.status is Status.WITNESSED else EXIT_DISAGREE
    reproduces = rc == expected
    data = {
        "id": node.id,
        "trial": node.trial,
        "exit_code": rc,
        "expected_exit": expected,
        "recorded_status": node.status.value,
        "reproduces": reproduces,
        "trial_stdout": proc.stdout.strip(),  # the regenerated disagreement, not stored
        "stderr_tail": proc.stderr.strip()[-400:],
    }
    emit(args, data, f"#{node.id} replay rc={rc} expected={expected} reproduces={reproduces}")
    return EXIT_OK if reproduces else EXIT_UNDECODED


def cmd_codes(args: argparse.Namespace) -> int:
    data = {str(code): desc for code, desc in sorted(EXIT_CODES.items())}
    human = "\n".join(f"{code:>3}  {desc}" for code, desc in sorted(EXIT_CODES.items()))
    emit(args, data, human)
    return EXIT_OK


# -- parser -------------------------------------------------------------------

def _add_common(parser: argparse.ArgumentParser, *, suppress: bool) -> None:
    """The I/O contract flags. Added to the top parser with real defaults, and to
    each subparser with SUPPRESS so `--json` works both before and after the
    subcommand without the subparser clobbering a value set up front."""
    d = argparse.SUPPRESS if suppress else None
    parser.add_argument("--json", action="store_true",
                        default=d if suppress else False, help="force JSON to stdout")
    parser.add_argument("--human", action="store_true",
                        default=d if suppress else False, help="force a human table")
    parser.add_argument("--pretty", action="store_true",
                        default=d if suppress else False, help="indent JSON output")
    parser.add_argument("--graph", default=d if suppress else DEFAULT_GRAPH,
                        help="hypothesis-graph file (env ABDUCTOR_GRAPH)")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="abductor",
        description="Execution-gated abductive evaluation. The tool caches and "
        "reconciles; the agent judges.",
        epilog=DRIVING_CONTRACT,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version="abductor 0.0.1")
    _add_common(p, suppress=False)  # flags usable before the subcommand

    common = argparse.ArgumentParser(add_help=False)
    _add_common(common, suppress=True)  # same flags usable after the subcommand
    sub = p.add_subparsers(dest="command", required=True)

    g = sub.add_parser("gate", parents=[common],
                       help="reconcile a candidate's accept-set against the baseline")
    g.add_argument("--believe", required=True, help="candidate's accept-set (file or -)")
    g.add_argument("--truth", required=True, help="baseline (base-branch) accept-set (file or -)")
    g.add_argument("--reference", default=None,
                   help="reference oracle = truth (file or -); enables diff-the-diff. "
                        "--truth is the base/foil; the candidate is scored against the "
                        "directional spec diff and a collapse code (11/12/13) names the axis "
                        "it collapsed onto (wide/narrow/both)")
    g.add_argument("--sketches", action="store_true", help="inputs are IBLT sketches, not sets")
    g.add_argument("--cells", type=int, default=None, help="initial sketch size")
    g.set_defaults(func=cmd_gate)

    s = sub.add_parser("sketch", parents=[common], help="encode a set into an O(cells) sketch")
    s.add_argument("infile", help="set of integers (file or -)")
    s.add_argument("--cells", type=int, default=256, help="sketch size (> expected difference)")
    s.add_argument("--k", type=int, default=4, help="cells touched per key")
    s.add_argument("--out", help="write sketch here instead of stdout")
    s.set_defaults(func=cmd_sketch)

    gr = sub.add_parser("graph", help="the inquiry's semantic memory")
    grs = gr.add_subparsers(dest="graph_cmd", required=True)
    gi = grs.add_parser("init", parents=[common], help="start a new inquiry")
    gi.add_argument("observation", help="the surprising observation under inquiry")
    gi.add_argument("--force", action="store_true", help="overwrite an existing graph")
    gi.set_defaults(func=cmd_graph_init)
    gsh = grs.add_parser("show", parents=[common], help="print the graph")
    gsh.add_argument("--markdown", action="store_true", help="render as markdown")
    gsh.set_defaults(func=cmd_graph_show)

    n = sub.add_parser("node", help="append or classify hypothesis nodes")
    ns = n.add_subparsers(dest="node_cmd", required=True)
    na = ns.add_parser("add", parents=[common], help="append a hypothesis (create / link)")
    na.add_argument("hypothesis")
    na.add_argument("--trial", required=True, help="the exact command that tests it")
    na.add_argument("--kill-if", required=True, dest="kill_if", help="the refuting condition")
    na.add_argument("--from", type=int, default=None, dest="from_node",
                    help="parent node id; the parent must be killed (generate-edge-from-kill)")
    na.add_argument("--mode", default="abduction",
                    choices=[m.value for m in Mode], help="reasoning mode")
    na.add_argument("--credence", type=float, default=0.5)
    na.set_defaults(func=cmd_node_add)
    npb = ns.add_parser("probe", parents=[common],
                        help="append a hypothesis, run its trial, classify by exit code; "
                        "the trial's output (the disagreement) comes back in trial_stdout")
    npb.add_argument("hypothesis")
    npb.add_argument("--trial", required=True,
                     help="the exact command that tests it (exit 0 witnesses, 10 kills, a "
                     "diff-the-diff collapse code 11/12/13 marks it collapsed); its stdout is "
                     "returned as trial_stdout, so no separate gate run is needed")
    npb.add_argument("--kill-if", dest="kill_if", default="trial reports a disagreement (exit 10)",
                     help="the refuting condition (default: the trial exits 10)")
    npb.add_argument("--from", type=int, default=None, dest="from_node",
                     help="parent node id; the parent must be killed")
    npb.add_argument("--credence", type=float, default=0.5)
    npb.set_defaults(func=cmd_node_probe)
    nk = ns.add_parser("kill", parents=[common], help="classify a node refuted")
    nk.add_argument("id", type=int)
    nk.add_argument("--outcome", required=True, help="what the trial showed")
    nk.set_defaults(func=cmd_node_kill)
    nw = ns.add_parser("witness", parents=[common], help="classify a node test-backed")
    nw.add_argument("id", type=int)
    nw.add_argument("--outcome", required=True, help="what the trial showed")
    nw.add_argument("--credence", type=float, default=0.96)
    nw.set_defaults(func=cmd_node_witness)
    npr = ns.add_parser("prune", parents=[common], help="drop a dead branch from the frontier")
    npr.add_argument("id", type=int)
    npr.set_defaults(func=cmd_node_prune)

    r = sub.add_parser("replay", parents=[common],
                       help="re-run a node's recorded trial and check it reproduces")
    r.add_argument("id", type=int)
    r.set_defaults(func=cmd_replay)

    c = sub.add_parser("codes", parents=[common], help="print the exit-code verdict table")
    c.set_defaults(func=cmd_codes)

    return p


def main(argv: list[str] | None = None) -> int:
    raw = list(argv) if argv is not None else sys.argv[1:]
    args = build_parser().parse_args(raw)
    args._argv = raw  # exact argv, recorded into gate provenance for replay/audit
    try:
        return args.func(args)
    except BrokenPipeError:
        return EXIT_OK
    except Exception as e:  # noqa: BLE001
        warn(str(e))
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
