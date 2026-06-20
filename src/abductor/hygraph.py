"""The hypothesis graph — a typed, append-only semantic memory of an inquiry.

A debugging agent's working memory, externalized. Each node is a falsifiable
hypothesis bound to a trial; each edge is a kill that names the next hypothesis.
The graph is the thing a stranger replays instead of a verdict they must trust.

CRUD-like operations (from *The Hypothesis Graph*, june.kim):

  create  abduce()       append a hypothesis with its kill condition and trial
  read    frontier()/replay()  query open nodes; reconstruct a node from its trial
  update  kill()/witness()     classify a node by its trial's outcome (write-once)
  link    from_kill()    a dead hypothesis names its successor (generate-edge-from-kill)
  delete  prune()        drop a dead branch from the frontier; the record stays

Soundness invariant: every node is reconstructible from its recorded trial by
someone who does not trust the author. ``replay()`` enforces it literally.

The convenience methods are for *agents who are debugging*: ``probe()`` runs the
abduce -> test -> classify cycle in one call against a gate and hands back the
counterexamples so the next hypothesis can be formed.

The graph is small enough to live in memory: only the reasoning skeleton is kept
(hypotheses, trial commands, verdicts), never the diffs or trial output, which are
regenerable by replay. A complete inquiry is a few hundred bytes to tens of KB, so
this object *is* the cache — no database, no index. ``save()``/``load()`` are
checkpointing for a fresh process, not a store.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable, Protocol


class GateLike(Protocol):
    """What ``probe()`` needs from a gate: a case space and a check that returns
    an object exposing ``mishandled() -> list``. The graph never sees the answer
    key, only the disagreement the gate reports."""

    cases: list
    span: str

    def check(self, candidate: Callable[[int], bool]) -> "object": ...


class Mode(str, Enum):
    ABDUCTION = "abduction"   # proposes content, untested
    DEDUCTION = "deduction"   # traces consequences
    INDUCTION = "induction"   # tests against the world


class Status(str, Enum):
    OPEN = "open"
    KILLED = "killed"
    WITNESSED = "witnessed"
    PRUNED = "pruned"
    COLLAPSED = "collapsed"   # diff-the-diff: candidate collapsed onto one branch
                              # (non-terminal — names a split, can link a successor)


# Credence is capped by the mode that earned the belief: abduction proposes and
# stays low; a test-backed induction may rise. The cap travels with the type so a
# reader in another window knows what the node is worth without re-deriving it.
CREDENCE_CAP: dict[Mode, float] = {
    Mode.ABDUCTION: 0.50,
    Mode.DEDUCTION: 0.90,
    Mode.INDUCTION: 0.97,
}


# A diff-the-diff verdict -> the node status it earns. A collapse is non-terminal
# (COLLAPSED can name a successor); a core error is a kill; matching truth witnesses.
# This routes status only; the gate alone decides the verdict (see cli._diff_the_diff).
BRANCH_VERDICT_STATUS: dict[str, Status] = {
    "pass": Status.WITNESSED,
    "disagree": Status.KILLED,
    "collapse_wide": Status.COLLAPSED,
    "collapse_narrow": Status.COLLAPSED,
    "collapse_both": Status.COLLAPSED,
}


@dataclass
class AxisOutcome:
    """The offending case-IDs on one axis of a diff-the-diff check.

    ``axis`` is one of ``over_wide`` (cases the candidate wrongly accepts, riding the
    BASE\\REF axis), ``over_narrow`` (cases it wrongly drops, riding REF\\BASE), or
    ``core`` (errors where the two oracles agree). ``cases`` are the exact IDs the
    gate reported, so the node is auditable per axis, not just per verdict."""

    axis: str
    cases: list[int]


@dataclass
class Node:
    id: int
    hypothesis: str
    mode: Mode
    trial: str                # the perturbation, stated as an exact command
    kill_if: str              # the condition under which this hypothesis dies
    credence: float
    status: Status = Status.OPEN
    outcome: str | None = None
    parent_id: int | None = None
    expected_exit: int | None = None  # exit code that defines reproduction (set by probe)
    # diff-the-diff branch structure — set only for a second-order check, None otherwise.
    # ``verdict`` is the directional verdict as a first-class, queryable field (never
    # parsed back out of the free-text ``outcome``); ``axes`` carries the per-axis
    # offending case-IDs the gate reported.
    verdict: str | None = None
    axes: list[AxisOutcome] | None = None

    def cap(self, value: float) -> float:
        return min(value, CREDENCE_CAP[self.mode])


@dataclass
class HypothesisGraph:
    """An append-only graph of hypothesis nodes for a single inquiry."""

    observation: str
    nodes: list[Node] = field(default_factory=list)
    # Replay material: id -> a zero-arg thunk that re-runs the recorded trial and
    # returns its outcome. Kept beside the node so replay() needs no live context.
    _replay: dict[int, Callable[[], object]] = field(default_factory=dict)
    _recorded: dict[int, object] = field(default_factory=dict)

    # -- create ----------------------------------------------------------------
    def abduce(
        self,
        hypothesis: str,
        *,
        trial: str,
        kill_if: str,
        parent: Node | int | None = None,
        credence: float = 0.5,
        mode: Mode = Mode.ABDUCTION,
    ) -> Node:
        """Append a node. Nodes append; nothing is overwritten."""
        node = Node(
            id=len(self.nodes),
            hypothesis=hypothesis,
            mode=mode,
            trial=trial,
            kill_if=kill_if,
            credence=0.0,
            parent_id=_id_of(parent),
        )
        node.credence = node.cap(credence)
        self.nodes.append(node)
        return node

    # -- read ------------------------------------------------------------------
    def get(self, node: Node | int) -> Node:
        return self.nodes[_id_of(node)]

    def frontier(self) -> list[Node]:
        """Open hypotheses still under test — the working set, pruned excluded."""
        return [n for n in self.nodes if n.status is Status.OPEN]

    def witnessed(self) -> list[Node]:
        return [n for n in self.nodes if n.status is Status.WITNESSED]

    def replay(self, node: Node | int) -> tuple[bool, object, object]:
        """Reconstruct a node from its recorded trial, distrusting the author.

        Re-runs the stored trial against a fresh world and compares the result to
        what the node recorded. Returns (matches, recorded, replayed). The
        soundness invariant holds iff this matches for every load-bearing node.
        """
        nid = _id_of(node)
        if nid not in self._replay:
            raise ValueError(f"node {nid} has no recorded trial to replay")
        replayed = self._replay[nid]()
        recorded = self._recorded[nid]
        return (replayed == recorded, recorded, replayed)

    # -- update ----------------------------------------------------------------
    def kill(self, node: Node | int, *, outcome: str) -> Node:
        """Classify a node as refuted. A verdict is written once."""
        n = self.get(node)
        _assert_open(n)
        n.status = Status.KILLED
        n.outcome = outcome
        n.credence = 0.0
        return n

    def collapse(self, node: Node | int, *, outcome: str) -> Node:
        """Classify a node as a branch collapse (diff-the-diff).

        A non-terminal verdict distinct from kill: the candidate is right on the
        agreement core but collapsed onto one branch of a genuine spec divergence.
        It is not refuted (the direction is the next move's signal), so it carries a
        status of its own and, like a kill, can name a successor via ``from_kill``.
        """
        n = self.get(node)
        _assert_open(n)
        n.status = Status.COLLAPSED
        n.outcome = outcome
        n.credence = 0.0
        return n

    def annotate_branch(
        self,
        node: Node | int,
        *,
        verdict: str,
        expected_exit: int | None = None,
        over_wide: Iterable[int] = (),
        over_narrow: Iterable[int] = (),
        core: Iterable[int] = (),
    ) -> Node:
        """Attach diff-the-diff branch structure to an already-classified node.

        The verdict and the per-axis offending case-IDs become first-class, queryable
        fields on the node — the directional signal is *not* buried in the free-text
        ``outcome``. Used by the CLI's ``node probe`` to enrich a node it has already
        classified (witnessed / killed / collapsed) with the structure the gate
        reported, so the recorded node is auditable per axis. Status is untouched here;
        only the gate decides the verdict and only the classifiers set the status."""
        n = self.get(node)
        n.verdict = verdict
        if expected_exit is not None:
            n.expected_exit = expected_exit
        axes = [
            AxisOutcome(name, list(cases))
            for name, cases in (
                ("over_wide", over_wide),
                ("over_narrow", over_narrow),
                ("core", core),
            )
            if list(cases)
        ]
        n.axes = axes or None
        return n

    def branch(
        self,
        hypothesis: str,
        *,
        trial: str,
        verdict: str,
        expected_exit: int,
        over_wide: Iterable[int] = (),
        over_narrow: Iterable[int] = (),
        core: Iterable[int] = (),
        parent: Node | int | None = None,
        credence: float = 0.5,
        kill_if: str = "the candidate's error Δ rides the over-wide or over-narrow axis",
        replay: Callable[[], object] | None = None,
    ) -> Node:
        """Record a diff-the-diff check as one replayable branch node, in one call.

        Appends the hypothesis, classifies it by the gate's directional ``verdict``
        (pass -> witnessed, disagree -> killed, collapse_* -> collapsed), and attaches
        the directional structure (``verdict`` + per-axis case-IDs). The node satisfies
        the replay invariant: it stores a thunk that re-runs the recorded ``trial`` (the
        exact ``gate --reference`` command) and the exit code it must reproduce, so a
        stranger reconstructs the verdict by re-running the trial — ``replay()`` returns
        a match iff the recorded exit comes back. The thunk is overridable for tests."""
        status = BRANCH_VERDICT_STATUS.get(verdict)
        if status is None:
            raise ValueError(
                f"unknown diff-the-diff verdict {verdict!r}; "
                f"expected one of {sorted(BRANCH_VERDICT_STATUS)}"
            )
        node = self.abduce(
            hypothesis, trial=trial, kill_if=kill_if, parent=parent, credence=credence
        )
        outcome = f"diff-the-diff: {verdict} (exit {expected_exit})"
        if status is Status.WITNESSED:
            self.witness(node, outcome=outcome)
        elif status is Status.KILLED:
            self.kill(node, outcome=outcome)
        else:
            self.collapse(node, outcome=outcome)
        self.annotate_branch(
            node, verdict=verdict, expected_exit=expected_exit,
            over_wide=over_wide, over_narrow=over_narrow, core=core,
        )
        self._replay[node.id] = replay or (lambda t=trial: _exit_of(t))
        self._recorded[node.id] = expected_exit
        return node

    def witness(self, node: Node | int, *, outcome: str, credence: float = 0.96) -> Node:
        """Classify a node as test-backed; credence rises, capped by its mode."""
        n = self.get(node)
        _assert_open(n)
        n.status = Status.WITNESSED
        n.outcome = outcome
        # A witnessing trial is inductive; the cap follows the mode that earned it.
        n.mode = Mode.INDUCTION if n.mode is Mode.ABDUCTION else n.mode
        n.credence = n.cap(credence)
        return n

    # -- link ------------------------------------------------------------------
    def from_kill(
        self, dead: Node | int, hypothesis: str, *, trial: str, kill_if: str, credence: float = 0.5
    ) -> Node:
        """generate-edge-from-kill: a dead hypothesis names its successor.

        The manner of the parent's death is what suggests the next node, so the
        graph extends itself with no external controller deciding where to look.
        """
        parent = self.get(dead)
        if parent.status not in (Status.KILLED, Status.COLLAPSED):
            raise ValueError("only a killed or collapsed hypothesis can name a successor")
        return self.abduce(
            hypothesis, trial=trial, kill_if=kill_if, parent=parent, credence=credence
        )

    # -- delete ----------------------------------------------------------------
    def prune(self, node: Node | int) -> Node:
        """Drop a dead branch from the frontier; its record stays replayable."""
        n = self.get(node)
        n.status = Status.PRUNED
        return n

    # -- convenience for debugging agents -------------------------------------
    def probe(
        self,
        hypothesis: str,
        candidate: Callable[[int], bool],
        gate: GateLike,
        *,
        parent: Node | int | None = None,
    ) -> tuple[Node, list[int]]:
        """One-call abduce -> test -> classify against a gate.

        Creates the hypothesis node, runs the gate over the case space (the
        trial), records replay material, and classifies the node killed or
        witnessed by the disagreement. Returns (node, counterexamples) so the
        agent forms its next hypothesis from the manner of death.
        """
        name = getattr(candidate, "__name__", "candidate")
        node = self.abduce(
            hypothesis,
            trial=f"gate.check({name}) over {gate.span}",
            kill_if="any case in the symmetric difference (false +/- vs baseline)",
            parent=parent,
        )
        result = gate.check(candidate)
        mishandled = result.mishandled()

        # Record replay material: the trial reruns deterministically from here.
        self._replay[node.id] = lambda c=candidate, g=gate: g.check(c).mishandled()
        self._recorded[node.id] = mishandled

        if mishandled:
            head = ", ".join(str(x) for x in mishandled[:5])
            more = "" if len(mishandled) <= 5 else f", +{len(mishandled) - 5} more"
            self.kill(node, outcome=f"{len(mishandled)} mishandled: {head}{more}")
        else:
            self.witness(node, outcome=f"0 mishandled across {len(gate.cases)} cases")
        return node, mishandled

    # -- persistence (the cache the tool owns) --------------------------------
    def to_dict(self) -> dict:
        return {
            "observation": self.observation,
            "nodes": [
                {
                    "id": n.id,
                    "hypothesis": n.hypothesis,
                    "mode": n.mode.value,
                    "trial": n.trial,
                    "kill_if": n.kill_if,
                    "credence": n.credence,
                    "status": n.status.value,
                    "outcome": n.outcome,
                    "parent_id": n.parent_id,
                    "expected_exit": n.expected_exit,
                    "verdict": n.verdict,
                    "axes": None if n.axes is None
                    else [{"axis": a.axis, "cases": a.cases} for a in n.axes],
                }
                for n in self.nodes
            ],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "HypothesisGraph":
        g = cls(observation=d["observation"])
        for nd in d["nodes"]:
            g.nodes.append(
                Node(
                    id=nd["id"],
                    hypothesis=nd["hypothesis"],
                    mode=Mode(nd["mode"]),
                    trial=nd["trial"],
                    kill_if=nd["kill_if"],
                    credence=nd["credence"],
                    status=Status(nd["status"]),
                    outcome=nd["outcome"],
                    parent_id=nd["parent_id"],
                    expected_exit=nd.get("expected_exit"),
                    verdict=nd.get("verdict"),
                    axes=None if nd.get("axes") is None
                    else [AxisOutcome(a["axis"], a["cases"]) for a in nd["axes"]],
                )
            )
        return g

    def save(self, path: str | Path) -> None:
        """Write the record crash-safely. JSON is the replay substrate; a markdown
        sibling is the human-inspectable audit surface, kept current on every save.

        Writes are atomic (temp file + fsync + os.replace), so a crash mid-write
        never leaves a truncated or corrupt record: a reader sees either the old
        file or the new one, never a half-written one. The in-memory graph shares
        the agent's lifecycle and is not recovered on its own; this file is the
        only thing that outlives a crash, so it is the only thing made durable."""
        p = Path(path)
        _atomic_write(p, json.dumps(self.to_dict(), indent=2) + "\n")
        _atomic_write(p.with_suffix(".md"), self.to_markdown() + "\n")

    def match(self, hypothesis: str, trial: str, parent_id: int | None) -> Node | None:
        """Find an existing node with identical content, so a retried append is
        idempotent rather than duplicating the node."""
        for n in self.nodes:
            if n.hypothesis == hypothesis and n.trial == trial and n.parent_id == parent_id:
                return n
        return None

    @classmethod
    def load(cls, path: str | Path) -> "HypothesisGraph":
        return cls.from_dict(json.loads(Path(path).read_text()))

    # -- serialization ---------------------------------------------------------
    def to_markdown(self) -> str:
        """The graph as the markdown file the harness owns — no DB, no index."""
        glyph = {
            Status.OPEN: "○",
            Status.KILLED: "✗",
            Status.WITNESSED: "✓",
            Status.PRUNED: "·",
            Status.COLLAPSED: "⋈",
        }
        lines = [f"# Inquiry: {self.observation}", ""]
        for n in self.nodes:
            arrow = "" if n.parent_id is None else f" (from kill of #{n.parent_id})"
            meta = f"- mode: {n.mode.value}  ·  credence: {n.credence:.2f}  ·  status: {n.status.value}"
            if n.expected_exit is not None:
                meta += f"  ·  reproduces at exit {n.expected_exit}"
            lines += [
                f"## {glyph[n.status]} #{n.id} {n.hypothesis}{arrow}",
                meta,
                f"- trial: `{n.trial}`",
                f"- kill if: {n.kill_if}",
                f"- outcome: {n.outcome or '(untested)'}",
            ]
            if n.verdict is not None:
                # The directional verdict and which axis it collapsed onto — the audit
                # surface shows *why* a wide-but-broken fix died, not just that it did.
                lines.append(f"- diff-the-diff verdict: {n.verdict}")
                for a in n.axes or []:
                    lines.append(f"  - {a.axis}: {a.cases}")
            lines.append("")
        return "\n".join(lines)


def _exit_of(trial: str) -> int:
    """Re-run a recorded trial command and return its exit code. The default replay
    thunk for a branch node: a stranger reconstructs the verdict by re-running the
    exact ``gate --reference`` command, and ``replay()`` checks the recorded exit
    comes back. Trials may use process substitution ``<(...)``, so run under bash."""
    return subprocess.run(  # noqa: S602  (the trial is the node's own recorded command)
        trial, shell=True, executable="/bin/bash", capture_output=True, text=True
    ).returncode


def _id_of(node: Node | int | None) -> int | None:
    if node is None:
        return None
    return node.id if isinstance(node, Node) else node


def _assert_open(n: Node) -> None:
    if n.status is not Status.OPEN:
        raise ValueError(f"node #{n.id} already classified as {n.status.value} (verdict is write-once)")


def _atomic_write(path: Path, text: str) -> None:
    """Write text so a crash can't corrupt the target: stage to a temp file in the
    same directory, flush+fsync, then os.replace (atomic on POSIX)."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent or "."), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
