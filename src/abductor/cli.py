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

# The verdict table, published so an agent never scrapes docs for it.
EXIT_CODES = {
    EXIT_OK: "ok: success / agreement (a hypothesis witnessed)",
    EXIT_ERROR: "error: unexpected failure",
    2: "usage: bad arguments",
    EXIT_NOTFOUND: "not_found: graph or node missing",
    EXIT_UNDECODED: "undecoded: sketch too small, or a replay did not reproduce",
    EXIT_DISAGREE: "disagree: a disagreement was found (a hypothesis killed)",
}

DEFAULT_GRAPH = os.environ.get("ABDUCTOR_GRAPH", "inquiry.json")
BASH = "/bin/bash"  # trials may use process substitution <(...), which needs bash


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


def read_ints(path: str) -> set[int]:
    """Read a whitespace-separated set of integers from a file or '-' (stdin)."""
    text = sys.stdin.read() if path == "-" else open(path).read()
    return {int(tok) for tok in text.split()}


def read_json(path: str) -> dict:
    return json.loads(sys.stdin.read() if path == "-" else open(path).read())


# -- gate: reconcile two accept-sets (the parts-bin XOR) ----------------------

def cmd_gate(args: argparse.Namespace) -> int:
    if args.sketches:
        a = IBLT.from_dict(read_json(args.believe))
        b = IBLT.from_dict(read_json(args.truth))
        fp, fn, decoded = reconcile_sketches(a, b)
    else:
        believed, truth = read_ints(args.believe), read_ints(args.truth)
        fp, fn, decoded = reconcile(believed, truth, cells=args.cells)

    if not decoded:
        warn("sketch too small to decode the difference; raise --cells")
        emit(args, {"decoded": False}, "undecoded: raise --cells")
        return EXIT_UNDECODED

    fp_l, fn_l = sorted(fp), sorted(fn)
    agree = not fp_l and not fn_l
    data = {
        "agree": agree,
        "delta": len(fp_l) + len(fn_l),
        "false_positives": fp_l,  # believed leap, baseline says no
        "false_negatives": fn_l,  # baseline says leap, candidate missed
        "decoded": True,
    }
    if agree:
        human = "agree: 0 disagreements"
    else:
        human = f"disagree: {data['delta']} cases  +{fp_l[:5]} -{fn_l[:5]}"
    emit(args, data, human)
    return EXIT_OK if agree else EXIT_DISAGREE


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
        warn(f"{args.graph} exists; pass --force to overwrite")
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


def cmd_node_add(args: argparse.Namespace) -> int:
    g = _load(args)
    if g is None:
        return EXIT_NOTFOUND
    try:
        if args.from_node is not None:
            node = g.from_kill(
                args.from_node, args.hypothesis, trial=args.trial,
                kill_if=args.kill_if, credence=args.credence,
            )
        else:
            node = g.abduce(
                args.hypothesis, trial=args.trial, kill_if=args.kill_if,
                credence=args.credence, mode=Mode(args.mode),
            )
    except (ValueError, IndexError) as e:
        warn(str(e))
        return EXIT_ERROR
    g.save(args.graph)
    emit(args, _node_dict(g, node), f"added #{node.id} ({node.mode.value})")
    return EXIT_OK


def _classify(args: argparse.Namespace, witness: bool) -> int:
    g = _load(args)
    if g is None:
        return EXIT_NOTFOUND
    try:
        node = (g.witness(args.id, outcome=args.outcome, credence=args.credence)
                if witness else g.kill(args.id, outcome=args.outcome))
    except (ValueError, IndexError) as e:
        warn(str(e))
        return EXIT_ERROR
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
    try:
        node = g.prune(args.id)
    except IndexError as e:
        warn(str(e))
        return EXIT_NOTFOUND
    g.save(args.graph)
    emit(args, _node_dict(g, node), f"#{node.id} pruned (record kept)")
    return EXIT_OK


def _run_trial(trial: str) -> subprocess.CompletedProcess:
    return subprocess.run(trial, shell=True, executable=BASH, capture_output=True, text=True)


def cmd_node_probe(args: argparse.Namespace) -> int:
    """Append a hypothesis, run its trial, and classify by the trial's exit code.

    The fused create -> test -> classify step. The mechanical rule: a trial exiting
    0 witnesses the node, 10 kills it; any other code is a broken trial, left open.
    The agent still supplies the hypothesis and the trial — only the bookkeeping is
    fused. The trial's exit code is recorded so `replay` can check exact reproduction.
    """
    g = _load(args)
    if g is None:
        return EXIT_NOTFOUND
    try:
        if args.from_node is not None:
            node = g.from_kill(args.from_node, args.hypothesis, trial=args.trial,
                               kill_if=args.kill_if, credence=args.credence)
        else:
            node = g.abduce(args.hypothesis, trial=args.trial, kill_if=args.kill_if,
                            credence=args.credence)
    except (ValueError, IndexError) as e:
        warn(str(e))
        return EXIT_ERROR

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
    else:
        node.outcome = f"trial errored (exit {rc}); left open"
    g.save(args.graph)
    result = _node_dict(g, node)
    result["exit_code"] = rc
    result["trial_stdout"] = proc.stdout.strip()  # transient: read it, do not expect it stored
    if rc not in (EXIT_OK, EXIT_DISAGREE):
        result["stderr_tail"] = proc.stderr.strip()[-400:]
    emit(args, result, f"#{node.id} probe rc={rc} -> {node.status.value}\n{proc.stdout.strip()}")
    return rc if rc in (EXIT_OK, EXIT_DISAGREE) else EXIT_ERROR


# -- replay: re-run a node's recorded trial command ---------------------------

def cmd_replay(args: argparse.Namespace) -> int:
    g = _load(args)
    if g is None:
        return EXIT_NOTFOUND
    try:
        node = g.get(args.id)
    except IndexError as e:
        warn(str(e))
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
    )
    p.add_argument("--version", action="version", version="abductor 0.0.1")
    _add_common(p, suppress=False)  # flags usable before the subcommand

    common = argparse.ArgumentParser(add_help=False)
    _add_common(common, suppress=True)  # same flags usable after the subcommand
    sub = p.add_subparsers(dest="command", required=True)

    g = sub.add_parser("gate", parents=[common],
                       help="reconcile a candidate's accept-set against the baseline")
    g.add_argument("--believe", required=True, help="candidate's accept-set (file or -)")
    g.add_argument("--truth", required=True, help="baseline accept-set (file or -)")
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
                        help="append a hypothesis, run its trial, and classify by exit code")
    npb.add_argument("hypothesis")
    npb.add_argument("--trial", required=True, help="the exact command that tests it (exit 0/10)")
    npb.add_argument("--kill-if", required=True, dest="kill_if", help="the refuting condition")
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
    args = build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    try:
        return args.func(args)
    except BrokenPipeError:
        return EXIT_OK
    except Exception as e:  # noqa: BLE001
        warn(str(e))
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
