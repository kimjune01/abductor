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
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Protocol


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


# Credence is capped by the mode that earned the belief: abduction proposes and
# stays low; a test-backed induction may rise. The cap travels with the type so a
# reader in another window knows what the node is worth without re-deriving it.
CREDENCE_CAP: dict[Mode, float] = {
    Mode.ABDUCTION: 0.50,
    Mode.DEDUCTION: 0.90,
    Mode.INDUCTION: 0.97,
}


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
        if parent.status is not Status.KILLED:
            raise ValueError("only a killed hypothesis can name a successor")
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
                )
            )
        return g

    def save(self, path: str | Path) -> None:
        """Write the record. JSON is the replay substrate; a markdown sibling is
        the human-inspectable audit surface, kept current on every save so an
        auditor never has to run a command to read the inquiry."""
        p = Path(path)
        p.write_text(json.dumps(self.to_dict(), indent=2) + "\n")
        p.with_suffix(".md").write_text(self.to_markdown() + "\n")

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
                "",
            ]
        return "\n".join(lines)


def _id_of(node: Node | int | None) -> int | None:
    if node is None:
        return None
    return node.id if isinstance(node, Node) else node


def _assert_open(n: Node) -> None:
    if n.status is not Status.OPEN:
        raise ValueError(f"node #{n.id} already classified as {n.status.value} (verdict is write-once)")
